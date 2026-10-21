// Signal Desk copier for MetaTrader 4.
// OILCash and BRENTCash are MT5 markets at XM. This copier will report
// "symbol not found" for those, and the website will say so.
// Allow WebRequest for your desk URL under Tools → Options → Expert Advisors.

#property copyright "Signal Desk"
#property version   "1.13"
#property strict
#property description "Places Signal Desk orders on the XM account this terminal is logged into."

input string ApiBase          = "https://YOUR-APP-URL";
input string ApiKey           = "";
input int    PollSeconds      = 10;
input int    Magic            = 56021;
input int    SlippagePoints   = 30;
input int    MaxSpreadPoints  = 40;
input double MaxLots          = 0;
input double BreakEvenProfitUSD = 4.0; //4.0 Floating profit that moves the stop to the entry price. 0 = off.
input double LockProfitTriggerUSD = 0; //5.0 Floating profit that locks a winner. 0 = off.
input double LockProfitUSD = 1.0; // Profit the stop locks in once the trigger is reached.
input double SpreadWidenRatio = 0.15; // When the spread is this fraction of the stop, push the stop out by the spread.

string LastNote = "Starting.";
string AccountKind = "";

void ReadAccountKind(string text)
{
   if(StringFind(text, "account_type=micro") >= 0) AccountKind = "micro";
   else if(StringFind(text, "account_type=standard") >= 0) AccountKind = "standard";
}

void CheckBreakEven();

int OnInit()
{
   if(StringLen(ApiKey) < 8 || StringLen(ApiBase) < 12)
   {
      Alert("Signal Desk: set ApiBase to your website and paste the copier key.");
      return(INIT_FAILED);
   }
   EventSetTimer((PollSeconds < 5) ? 5 : PollSeconds);
   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason) { EventKillTimer(); }

void OnTimer()
{
   CheckBreakEven();
   Poll();
}

void OnTick()
{
   CheckBreakEven();
}

string BaseUrl()
{
   string url = ApiBase;
   StringTrimLeft(url);
   StringTrimRight(url);
   int n = StringLen(url);
   if(n > 0 && StringGetCharacter(url, n - 1) == '/')
      url = StringSubstr(url, 0, n - 1);
   return url;
}

void Paint()
{
   Comment("Signal Desk\n", LastNote, "\n", TimeToString(TimeCurrent(), TIME_DATE|TIME_SECONDS));
}

bool Http(string method, string path, string body, string &response, int &code)
{
   char data[];
   char result[];
   string resultHeaders;
   if(StringLen(body) == 0)
      ArrayResize(data, 0);
   else
   {
      int n = StringToCharArray(body, data, 0, WHOLE_ARRAY, CP_UTF8);
      if(n > 0) ArrayResize(data, n - 1);
   }
   string headers = "X-Api-Key: " + ApiKey + "\r\nContent-Type: text/plain\r\n";
   ResetLastError();
   code = WebRequest(method, BaseUrl() + path, headers, 10000, data, result, resultHeaders);
   if(code == -1)
   {
      LastNote = "WebRequest was blocked (error " + IntegerToString(GetLastError()) + "). Allow this URL:\n" + BaseUrl();
      Paint();
      return false;
   }
   response = CharArrayToString(result, 0, WHOLE_ARRAY, CP_UTF8);
   if(code == 401)
   {
      LastNote = "The copier key was rejected. Create a new key on the website and paste it into ApiKey.";
      Paint();
      return false;
   }
   if(code < 200 || code >= 300)
   {
      LastNote = "The desk returned HTTP " + IntegerToString(code) + ".";
      Paint();
      return false;
   }
   return true;
}

bool UseSymbol(string name)
{
   if(StringLen(name) < 2) return false;
   if(!SymbolSelect(name, true)) return false;
   if(MarketInfo(name, MODE_TRADEALLOWED) == 0) return false;
   return (MarketInfo(name, MODE_BID) > 0 || MarketInfo(name, MODE_ASK) > 0);
}

bool LooksMicro(string name)
{
   string n = name;
   StringToUpper(n);
   if(StringFind(n, "MICRO") >= 0) return true;
   int len = StringLen(n);
   if(len >= 3 && StringFind(n, "M#") == len - 2) return true;
   if(len >= 3 && StringFind(n, ".M") == len - 2) return true;
   if(len >= 2 && StringGetCharacter(n, len - 1) == 'M')
   {
      ushort prev = StringGetCharacter(n, len - 2);
      return (prev < '0' || prev > '9');
   }
   return false;
}

bool IsForexName(string name)
{
   if(StringFind(name, "GOLD") >= 0 || StringFind(name, "XAU") >= 0) return false;
   if(StringFind(name, "OIL") >= 0 || StringFind(name, "BRENT") >= 0 || StringFind(name, "WTI") >= 0) return false;
   return (StringFind(name, "USD") >= 0 || StringFind(name, "EUR") >= 0 || StringFind(name, "GBP") >= 0);
}

void NoteFxContract(string name, double contract, string &fxName, double &fxContract, string &microName, double &microContract)
{
   if(!IsForexName(name) || contract <= 0) return;
   if(contract >= 500.0 && contract <= 5000.0 && microContract <= 0)
   {
      microName = name;
      microContract = contract;
   }
   else if(contract >= 50000.0 && contract <= 200000.0 && fxContract <= 0)
   {
      fxName = name;
      fxContract = contract;
   }
}

bool PrefixMatch(string symbol, string alias)
{
   if(StringLen(alias) < 4) return false;
   if(StringFind(symbol, alias) != 0) return false;
   if(StringLen(symbol) == StringLen(alias)) return true;
   ushort ch = StringGetCharacter(symbol, StringLen(alias));
   return (ch == '#' || ch == '.' || ch == '-' || ch == '_');
}

bool IsAnchoredMarket(string name)
{
   string n = name;
   StringToUpper(n);
   return (StringFind(n, "GOLD") >= 0 || StringFind(n, "XAU") >= 0
      || StringFind(n, "SILVER") >= 0 || StringFind(n, "XAG") >= 0
      || StringFind(n, "OIL") >= 0 || StringFind(n, "BRENT") >= 0 || StringFind(n, "WTI") >= 0 || StringFind(n, "XTI") >= 0
      || StringFind(n, "NGAS") >= 0 || StringFind(n, "NATGAS") >= 0
      || StringFind(n, "COPPER") >= 0 || StringFind(n, "HGCOP") >= 0
      || StringFind(n, "SOY") >= 0 || StringFind(n, "SBEAN") >= 0);
}

string ResolveSymbol(string names, double entry)
{
   string options[];
   int count = StringSplit(names, ',', options);
   string exact = "";
   string exactCash = "";
   string exactMicro = "";
   string exactStd = "";
   for(int i = 0; i < count; i++)
   {
      string candidate = options[i];
      StringTrimLeft(candidate);
      StringTrimRight(candidate);
      if(candidate == "" || !UseSymbol(candidate)) continue;
      if(exact == "") exact = candidate;
      if(exactCash == "" && StringFind(candidate, "Cash") >= 0) exactCash = candidate;
      if(exactMicro == "" && LooksMicro(candidate)) exactMicro = candidate;
      if(exactStd == "" && !LooksMicro(candidate)) exactStd = candidate;
   }
   if(exactCash != "") return exactCash;
   if(AccountKind == "micro" && exactMicro != "") return exactMicro;
   if(AccountKind != "micro" && exactStd != "") return exactStd;
   if(exact != "") return exact;
   for(int pass = 0; pass < 2; pass++)
   {
      bool selectedOnly = (pass == 0);
      int total = SymbolsTotal(selectedOnly);
      for(int i = 0; i < total; i++)
      {
         string sym = SymbolName(i, selectedOnly);
         for(int a = 0; a < count; a++)
         {
            string alias = options[a];
            StringTrimLeft(alias);
            StringTrimRight(alias);
            if(alias != "" && PrefixMatch(sym, alias) && UseSymbol(sym)) return sym;
         }
      }
   }
   return "";
}

double QuoteScale(double signalPrice, double brokerPrice)
{
   if(signalPrice <= 0 || brokerPrice <= 0) return 1.0;
   double ratio = brokerPrice / signalPrice;
   if(ratio <= 0) return 1.0;
   double logR = MathLog10(ratio);
   double power = MathRound(logR);
   if(MathAbs(power) >= 1.0 && MathAbs(logR - power) <= MathLog10(1.8))
      return MathPow(10.0, power);
   return 1.0;
}

string DigitsOnly(string text)
{
   string out = "";
   int n = StringLen(text);
   for(int i = 0; i < n; i++)
   {
      ushort ch = StringGetCharacter(text, i);
      if(ch >= '0' && ch <= '9') out += ShortToString(ch);
   }
   return out;
}

string Heartbeat()
{
   string names[] = {
      "EURUSD","EURUSDm","EURUSDmicro","EURUSD#","EURUSDm#",
      "GBPUSD","GBPUSDm","GBPUSDmicro","GBPUSD#","GBPUSDm#",
      "USDJPY","USDJPYm","USDJPYmicro","USDJPY#","USDJPYm#",
      "USDCHF","USDCHFm","USDCHFmicro","USDCHF#","USDCHFm#",
      "AUDUSD","AUDUSDm","AUDUSDmicro","AUDUSD#","AUDUSDm#",
      "USDCAD","USDCADm","USDCADmicro","USDCAD#","USDCADm#",
      "NZDUSD","NZDUSDm","NZDUSDmicro","NZDUSD#","NZDUSDm#",
      "EURGBP","EURGBPm","EURGBPmicro","EURGBP#","EURGBPm#",
      "EURJPY","EURJPYm","EURJPYmicro","EURJPY#","EURJPYm#",
      "GBPJPY","GBPJPYm","GBPJPYmicro","GBPJPY#","GBPJPYm#",
      "GOLD","GOLD#","XAUUSD","XAUUSD#","GOLDmicro","GOLDm#","GOLDm","XAUUSDm#",
      "SILVER","SILVER#","XAGUSD","XAGUSD#","SILVERmicro","SILVERm#","SILVERm",
      "OILCash","OILCash#","OILCash.m","USOIL","WTI","WTIOILCash","XTIUSD",
      "BRENTCash","BRENTCash#","BRENTCash.m","UKOIL","XBRUSD",
      "HGCOP","HGCOP#","COPPER","COPPER#","COPPERCash","COPPERCash#","HGCOPPER",
      "NGASCash","NGASCash#","NATGASCash","NGAS","NGAS#","NATGAS","NGAS.c",
      "SBEAN","SBEAN#","SOYBEAN","SOYBEAN#","SOYBEANCash","SOYBEANCash#","SOY",
      "US30","US30Cash","US30Cash#","US30#","DJ30","USA30","US30.pro","US30.m","US30m#","US30Cashm#","WS30",
      "US100","US100Cash","US100Cash#","US100#","NAS100","USTECH","US100.pro","US100.m","US100m#","US100Cashm#",
      "US500","US500Cash","US500Cash#","US500#","SPX500","US500.pro","US500.m","US500m#","US500Cashm#",
      "GER40","GER40Cash","GER40Cash#","GER40#","DE40","GER30","GER40.pro","GER40.m","GER40m#","GER40Cashm#",
      "JP225","JP225Cash","JP225Cash#","JP225#","JPN225","JP225.pro","JP225.m","JP225m#","JP225Cashm#",
      "VOLX","VOLXCash","VOLXCash#","VIX","VOLX#","VIX#","VOLX.c","VIX.c",
      "USDX","USDXCash","USDXCash#","DXY","USDX#","DXY#","USDX.c"
   };
   string fxName = "";
   double fxContract = 0;
   string microFxName = "";
   double microFxContract = 0;
   string specs = "";
   for(int i = 0; i < ArraySize(names); i++)
   {
      string name = names[i];
      if(!UseSymbol(name)) continue;
      double contract = MarketInfo(name, MODE_LOTSIZE);
      double tickSize = MarketInfo(name, MODE_TICKSIZE);
      double tickValue = MarketInfo(name, MODE_TICKVALUE);
      if(contract <= 0 || tickSize <= 0) continue;
      NoteFxContract(name, contract, fxName, fxContract, microFxName, microFxContract);
      int digits = (int)MarketInfo(name, MODE_DIGITS);
      specs += "spec=" + name
         + "|" + DoubleToString(contract, 2)
         + "|" + DoubleToString(tickSize, 8)
         + "|" + DoubleToString(tickValue, 6)
         + "|" + DoubleToString(MarketInfo(name, MODE_MINLOT), 2)
         + "|" + DoubleToString(MarketInfo(name, MODE_MAXLOT), 2)
         + "|" + DoubleToString(MarketInfo(name, MODE_LOTSTEP), 2)
         + "|" + IntegerToString(digits)
         + "|" + DoubleToString(MarketInfo(name, MODE_BID), digits)
         + "|" + DoubleToString(MarketInfo(name, MODE_ASK), digits)
         + "\n";
   }
   for(int i = 0; i < ArraySize(names); i++)
   {
      string alt = names[i] + ".micro";
      if(StringFind(specs, "spec=" + alt + "|") >= 0) continue;
      if(!UseSymbol(alt)) continue;
      double contract = MarketInfo(alt, MODE_LOTSIZE);
      double tickSize = MarketInfo(alt, MODE_TICKSIZE);
      double tickValue = MarketInfo(alt, MODE_TICKVALUE);
      if(contract <= 0 || tickSize <= 0) continue;
      NoteFxContract(alt, contract, fxName, fxContract, microFxName, microFxContract);
      int digits = (int)MarketInfo(alt, MODE_DIGITS);
      specs += "spec=" + alt
         + "|" + DoubleToString(contract, 2)
         + "|" + DoubleToString(tickSize, 8)
         + "|" + DoubleToString(tickValue, 6)
         + "|" + DoubleToString(MarketInfo(alt, MODE_MINLOT), 2)
         + "|" + DoubleToString(MarketInfo(alt, MODE_MAXLOT), 2)
         + "|" + DoubleToString(MarketInfo(alt, MODE_LOTSTEP), 2)
         + "|" + IntegerToString(digits)
         + "|" + DoubleToString(MarketInfo(alt, MODE_BID), digits)
         + "|" + DoubleToString(MarketInfo(alt, MODE_ASK), digits)
         + "\n";
   }
   int watched = SymbolsTotal(true);
   for(int i = 0; i < watched; i++)
   {
      string sym = SymbolName(i, true);
      if(StringFind(specs, "spec=" + sym + "|") >= 0) continue;
      if(!UseSymbol(sym)) continue;
      bool hit = LooksMicro(sym);
      if(!hit)
      {
         for(int a = 0; a < ArraySize(names); a++)
         {
            if(sym == names[a] || PrefixMatch(sym, names[a])) { hit = true; break; }
         }
      }
      if(!hit) continue;
      double contract = MarketInfo(sym, MODE_LOTSIZE);
      double tickSize = MarketInfo(sym, MODE_TICKSIZE);
      double tickValue = MarketInfo(sym, MODE_TICKVALUE);
      if(contract <= 0 || tickSize <= 0) continue;
      NoteFxContract(sym, contract, fxName, fxContract, microFxName, microFxContract);
      int digits = (int)MarketInfo(sym, MODE_DIGITS);
      specs += "spec=" + sym
         + "|" + DoubleToString(contract, 2)
         + "|" + DoubleToString(tickSize, 8)
         + "|" + DoubleToString(tickValue, 6)
         + "|" + DoubleToString(MarketInfo(sym, MODE_MINLOT), 2)
         + "|" + DoubleToString(MarketInfo(sym, MODE_MAXLOT), 2)
         + "|" + DoubleToString(MarketInfo(sym, MODE_LOTSTEP), 2)
         + "|" + IntegerToString(digits)
         + "|" + DoubleToString(MarketInfo(sym, MODE_BID), digits)
         + "|" + DoubleToString(MarketInfo(sym, MODE_ASK), digits)
         + "\n";
   }
   if(microFxContract > 0)
   {
      fxName = microFxName;
      fxContract = microFxContract;
   }
   return "platform=mt4\n"
      + "login=" + IntegerToString(AccountNumber()) + "\n"
      + "broker=" + AccountServer() + "\n"
      + "balance=" + DoubleToString(AccountBalance(), 2) + "\n"
      + "equity=" + DoubleToString(AccountEquity(), 2) + "\n"
      + "currency=" + AccountCurrency() + "\n"
      + "fx_contract=" + DoubleToString(fxContract, 2) + "\n"
      + "fx_symbol=" + fxName + "\n"
      + specs;
}

void Report(string id, string status, int ticket, double price, double lots, string symbol, string message)
{
   string body = "delivery_id=" + id + "\nstatus=" + status
      + "\nticket=" + (ticket > 0 ? IntegerToString(ticket) : "")
      + "\nfill_price=" + DoubleToString(price, 8)
      + "\nlots=" + DoubleToString(lots, 2)
      + "\nbroker_symbol=" + symbol
      + "\nmessage=" + message + "\n";
   string response;
   int code;
   Http("POST", "/api/ea/executions", body, response, code);
}

bool FindOrder(string comment, int &ticket, double &price, double &lots, string &symbol)
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != Magic) continue;
      if(OrderComment() != comment) continue;
      ticket = OrderTicket();
      price = OrderOpenPrice();
      lots = OrderLots();
      symbol = OrderSymbol();
      return true;
   }
   return false;
}

double FitLots(string symbol, double lots)
{
   double step = MarketInfo(symbol, MODE_LOTSTEP);
   double minv = MarketInfo(symbol, MODE_MINLOT);
   double maxv = MarketInfo(symbol, MODE_MAXLOT);
   if(step <= 0) step = 0.01;
   lots = MathFloor(lots / step + 1e-8) * step;
   lots = NormalizeDouble(lots, 2);
   if(lots + 1e-8 < minv) return 0;
   if(maxv > 0 && lots > maxv) lots = maxv;
   return lots;
}

void CloseLine(string id, string comment)
{
   int ticket = -1;
   double lots = 0;
   string symbol = "";
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != Magic) continue;
      if(StringFind(OrderComment(), comment) != 0) continue;
      int next = StringLen(comment);
      if(StringLen(OrderComment()) > next)
      {
         int ch = StringGetChar(OrderComment(), next);
         if(ch >= '0' && ch <= '9') continue;
      }
      ticket = OrderTicket();
      lots = OrderLots();
      symbol = OrderSymbol();
      break;
   }
   if(ticket < 0)
   {
      Report(id, "closed", 0, 0, 0, "", "already flat");
      LastNote = comment + " is already flat.";
      return;
   }
   if(!OrderSelect(ticket, SELECT_BY_TICKET, MODE_TRADES)) return;
   RefreshRates();
   double price = (OrderType() == OP_BUY) ? MarketInfo(symbol, MODE_BID) : MarketInfo(symbol, MODE_ASK);
   if(!OrderClose(ticket, lots, NormalizeDouble(price, (int)MarketInfo(symbol, MODE_DIGITS)), SlippagePoints, clrNONE))
   {
      LastNote = symbol + " close failed (" + IntegerToString(GetLastError()) + ").";
      return;
   }
   Report(id, "closed", ticket, price, lots, symbol, "closed on the opposite ICWR signal");
   LastNote = symbol + " closed, ticket " + IntegerToString(ticket) + ".";
}

void PlaceLine(string line)
{
   if(StringFind(line, "close|") == 0)
   {
      string bits[];
      int c = StringSplit(line, '|', bits);
      if(c >= 3) CloseLine(bits[1], bits[2]);
      return;
   }
   string parts[];
   int n = StringSplit(line, '|', parts);
   if(n < 9) return;
   string id = parts[0];
   string side = parts[1];
   double entry = StringToDouble(parts[3]);
   double sl = StringToDouble(parts[4]);
   double tp = StringToDouble(parts[5]);
   double lots = StringToDouble(parts[6]);
   double chase = StringToDouble(parts[7]);
   string comment = parts[8];
   StringTrimRight(comment);

   if(side == "close")
   {
      CloseLine(id, comment);
      return;
   }

   int existing = 0;
   double openPrice = 0, openLots = 0;
   string openSymbol = "";
   if(FindOrder(comment, existing, openPrice, openLots, openSymbol))
   {
      Report(id, "placed", existing, openPrice, openLots, openSymbol, "already open");
      LastNote = comment + " is already open.";
      return;
   }
   if(!IsTradeAllowed())
   {
      Report(id, "not_placed", 0, 0, 0, "", "AutoTrading is turned off in the terminal.");
      LastNote = "AutoTrading is off.";
      return;
   }
   if(MaxLots > 0 && lots > MaxLots + 1e-8)
   {
      Report(id, "not_placed", 0, 0, lots, "", "Above the MaxLots ceiling on this chart.");
      return;
   }
   string chosen = ResolveSymbol(parts[2], entry);
   if(chosen == "")
   {
      Report(id, "not_placed", 0, 0, 0, "", "None of the symbol names are on this platform.");
      LastNote = "No symbol for order " + id + ". Cash oil and Brent need MT5.";
      return;
   }
   bool anchored = IsAnchoredMarket(chosen);
   int spread = (int)MarketInfo(chosen, MODE_SPREAD);
   int digits = (int)MarketInfo(chosen, MODE_DIGITS);
   RefreshRates();
   double bid = MarketInfo(chosen, MODE_BID);
   double ask = MarketInfo(chosen, MODE_ASK);
   double spreadPrice = ask - bid;
   if(spreadPrice < 0) spreadPrice = 0;
   if(!anchored)
   {
      int maxSpread = MaxSpreadPoints;
      if(MaxSpreadPoints > 0 && (digits <= 2 || StringFind(chosen, "US30") >= 0 || StringFind(chosen, "US100") >= 0 || StringFind(chosen, "US500") >= 0 || StringFind(chosen, "GER40") >= 0 || StringFind(chosen, "JP225") >= 0 || StringFind(chosen, "VOLX") >= 0 || StringFind(chosen, "VIX") >= 0))
         maxSpread = MaxSpreadPoints * 15;
      if(MaxSpreadPoints > 0 && spread > maxSpread)
      {
         Report(id, "not_placed", 0, 0, 0, chosen, "Spread is wider than the copier allows.");
         return;
      }
   }
   lots = FitLots(chosen, lots);
   if(lots <= 0)
   {
      Report(id, "not_placed", 0, 0, 0, chosen, "The size is below this symbol's minimum.");
      return;
   }
   double price = (side == "buy") ? ask : bid;
   if(anchored && price > 0 && spreadPrice > price * 0.08)
   {
      Report(id, "not_placed", 0, price, lots, chosen, "Spread is too wide to price the stop.");
      LastNote = chosen + " spread is too wide to price the stop.";
      return;
   }
   if(!anchored && chase > 0 && MathAbs(price - entry) > chase)
   {
      Report(id, "not_placed", 0, price, lots, chosen, "Price moved away from the signal.");
      LastNote = chosen + " moved away from the signal.";
      return;
   }
   double point = MarketInfo(chosen, MODE_POINT);
   double scale = anchored ? QuoteScale(entry, price) : 1.0;
   double slDist = MathAbs(entry - sl) * scale;
   bool noTarget = (tp <= 0.0);
   double tpDist = noTarget ? 0.0 : MathAbs(entry - tp) * scale;
   double planned = slDist;
   if(anchored && SpreadWidenRatio > 0 && planned > 0 && spreadPrice > planned * SpreadWidenRatio)
      slDist += spreadPrice;
   double minDist = MarketInfo(chosen, MODE_STOPLEVEL) * point;
   if(minDist > 0 && (slDist < minDist || (!noTarget && tpDist < minDist)))
   {
      if(!anchored)
      {
         Report(id, "not_placed", 0, price, lots, chosen, "Stop or target is closer than the broker allows.");
         return;
      }
      if(slDist < minDist) slDist = minDist;
      if(!noTarget && tpDist < minDist) tpDist = minDist;
   }
   if(anchored && planned > 0 && slDist > planned)
   {
      double shrunk = FitLots(chosen, lots * planned / slDist);
      if(shrunk > 0) lots = shrunk;
   }
   double final_sl = (side == "buy") ? (price - slDist) : (price + slDist);
   double final_tp = noTarget ? 0.0 : ((side == "buy") ? (price + tpDist) : (price - tpDist));
   string fillNote = (anchored && slDist > planned + point) ? "filled, stop widened for the spread" : "filled";
   int cmd = (side == "buy") ? OP_BUY : OP_SELL;
   int ticket = OrderSend(chosen, cmd, lots, NormalizeDouble(price, digits), SlippagePoints, NormalizeDouble(final_sl, digits), NormalizeDouble(final_tp, digits), comment, Magic, 0, clrNONE);
   if(ticket < 0)
   {
      Report(id, "not_placed", 0, price, lots, chosen, "OrderSend error " + IntegerToString(GetLastError()));
      LastNote = chosen + " order was rejected (" + IntegerToString(GetLastError()) + ").";
      return;
   }
   if(OrderSelect(ticket, SELECT_BY_TICKET, MODE_TRADES))
      Report(id, "placed", ticket, OrderOpenPrice(), OrderLots(), chosen, fillNote);
   else
      Report(id, "placed", ticket, price, lots, chosen, fillNote);
   LastNote = chosen + " " + side + " filled, ticket " + IntegerToString(ticket) + ".";
}

double MoneyToPrice(string sym, double volume, double money)
{
   double tickSize = MarketInfo(sym, MODE_TICKSIZE);
   double tickValue = MarketInfo(sym, MODE_TICKVALUE);
   if(tickSize <= 0 || tickValue <= 0 || volume <= 0 || money <= 0) return 0;
   return money * tickSize / (tickValue * volume);
}

void CheckBreakEven()
{
   if(BreakEvenProfitUSD <= 0 && LockProfitTriggerUSD <= 0) return;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != Magic) continue;
      if(OrderType() != OP_BUY && OrderType() != OP_SELL) continue;

      double profit = OrderProfit();
      double openPrice = OrderOpenPrice();
      double currentSL = OrderStopLoss();
      double currentTP = OrderTakeProfit();
      int type = OrderType();
      string sym = OrderSymbol();
      int digits = (int)MarketInfo(sym, MODE_DIGITS);
      double point = MarketInfo(sym, MODE_POINT);
      string comment = OrderComment();
      int ticket = OrderTicket();
      double volume = OrderLots();
      RefreshRates();
      double bid = MarketInfo(sym, MODE_BID);
      double ask = MarketInfo(sym, MODE_ASK);
      if(bid <= 0 || ask <= 0) continue;

      string status = "";
      string message = "";
      double targetSL = 0;
      if(LockProfitTriggerUSD > 0 && LockProfitUSD > 0 && profit + 1e-8 >= LockProfitTriggerUSD)
      {
         double lockDist = MoneyToPrice(sym, volume, LockProfitUSD);
         if(lockDist <= 0) continue;
         targetSL = (type == OP_BUY) ? openPrice + lockDist : openPrice - lockDist;
         status = "sl_lock";
         message = sym + " #" + IntegerToString(ticket) + ": profit $" + DoubleToString(profit, 2)
            + ". SL moved to lock $" + DoubleToString(LockProfitUSD, 2) + ".";
      }
      else if(BreakEvenProfitUSD > 0 && profit + 1e-8 >= BreakEvenProfitUSD)
      {
         targetSL = openPrice;
         status = "sl_to_entry";
         message = sym + " #" + IntegerToString(ticket) + ": profit $" + DoubleToString(profit, 2) + ". SL moved to entry.";
      }
      else continue;

      double market = (type == OP_BUY) ? bid : ask;
      double spread = ask - bid;
      double cushion = (type == OP_BUY) ? (market - targetSL) : (targetSL - market);
      if(SpreadWidenRatio > 0 && spread > 0 && cushion > 0 && spread > cushion * SpreadWidenRatio)
      {
         if(type == OP_BUY) targetSL = MathMin(targetSL, market - spread);
         else targetSL = MathMax(targetSL, market + spread);
      }
      double stops = MathMax(MarketInfo(sym, MODE_STOPLEVEL), MarketInfo(sym, MODE_FREEZELEVEL)) * point;
      if(stops < spread) stops = spread;
      if(type == OP_BUY)
      {
         double limit = market - MathMax(stops, point);
         if(targetSL > limit) targetSL = limit;
         if(targetSL <= 0 || targetSL >= market) continue;
         if(currentSL > 0 && targetSL <= currentSL + point) continue;
      }
      else
      {
         double limit = market + MathMax(stops, point);
         if(targetSL < limit) targetSL = limit;
         if(targetSL <= market) continue;
         if(currentSL > 0 && targetSL >= currentSL - point) continue;
      }

      if(OrderModify(ticket, openPrice, NormalizeDouble(targetSL, digits), NormalizeDouble(currentTP, digits), 0, clrNONE))
      {
         Print(message);
         LastNote = message;
         Paint();
         Report(DigitsOnly(comment), status, ticket, NormalizeDouble(targetSL, digits), profit, sym, message);
      }
   }
}

void Poll()
{
   string response;
   int code = 0;
   if(!Http("POST", "/api/ea/heartbeat", Heartbeat(), response, code))
   {
      Paint();
      return;
   }
   ReadAccountKind(response);
   if(!Http("GET", "/api/ea/orders", "", response, code))
   {
      Paint();
      return;
   }
   int sep = StringFind(response, "---");
   if(sep < 0)
   {
      LastNote = "The desk reply was not understood.";
      Paint();
      return;
   }
   string head = StringSubstr(response, 0, sep);
   ReadAccountKind(head);
   if(StringFind(head, "mode=auto") < 0)
   {
      LastNote = "Connected. This account is signals only, so nothing will be placed.";
      Paint();
      return;
   }
   string rest = StringSubstr(response, sep + 3);
   string lines[];
   int n = StringSplit(rest, '\n', lines);
   int jobs = 0;
   for(int i = 0; i < n; i++)
   {
      string line = lines[i];
      StringReplace(line, "\r", "");
      StringTrimLeft(line);
      StringTrimRight(line);
      if(StringLen(line) < 3) continue;
      PlaceLine(line);
      jobs++;
   }
   if(jobs == 0)
      LastNote = "Connected. No order is waiting.";
   Paint();
}
