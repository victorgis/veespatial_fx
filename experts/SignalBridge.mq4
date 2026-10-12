// Signal Desk copier for MetaTrader 4.
// OILCash and BRENTCash are MT5 markets at XM. This copier will report
// "symbol not found" for those, and the website will say so.
// Allow WebRequest for your desk URL under Tools → Options → Expert Advisors.

#property copyright "Signal Desk"
#property version   "1.10"
#property strict
#property description "Places Signal Desk orders on the XM account this terminal is logged into."

input string ApiBase          = "https://YOUR-APP-URL";
input string ApiKey           = "";
input int    PollSeconds      = 10;
input int    Magic            = 56021;
input int    SlippagePoints   = 30;
input int    MaxSpreadPoints  = 40;
input double MaxLots          = 0;
input double BreakEvenProfitUSD = 2.0; // Profit in USD from MT4 to move Stop Loss to Entry (0 = off)

string LastNote = "Starting.";

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
      "GOLD","GOLD#","XAUUSD","XAUUSD#","GOLDmicro","GOLDm#",
      "SILVER","SILVER#","XAGUSD","XAGUSD#","SILVERmicro","SILVERm#","SILVERm",
      "OILCash","OILCash#","USOIL","WTI","WTIOILCash","XTIUSD",
      "BRENTCash","BRENTCash#","UKOIL","XBRUSD",
      "COPPER","COPPER#","COPPERm#","COPPERCash","COPPER.c","HGCOPPER",
      "NGAS","NGAS#","NGASCash","NGASCash#","NATGAS","NATGASCash","NGAS.c",
      "SOYBEAN","SOYBEAN#","SOYBEANCash","SOYBEANCash#","SOYBEAN.c","SOY",
      "US30","US30Cash","US30Cash#","US30#","DJ30","USA30","US30.pro","US30.m","WS30",
      "US100","US100Cash","US100Cash#","US100#","NAS100","USTECH","US100.pro","US100.m",
      "US500","US500Cash","US500Cash#","US500#","SPX500","US500.pro","US500.m",
      "GER40","GER40Cash","GER40Cash#","GER40#","DE40","GER30","GER40.pro","GER40.m",
      "JP225","JP225Cash","JP225Cash#","JP225#","JPN225","JP225.pro","JP225.m",
      "VOLX","VOLXCash","VOLXCash#","VIX","VOLX#","VIX#","VOLX.c","VIX.c",
      "USDX","USDXCash","USDXCash#","DXY","USDX#","DXY#","USDX.c"
   };
   string fxName = "";
   double fxContract = 0;
   string specs = "";
   for(int i = 0; i < ArraySize(names); i++)
   {
      string name = names[i];
      if(!UseSymbol(name)) continue;
      double contract = MarketInfo(name, MODE_LOTSIZE);
      double tickSize = MarketInfo(name, MODE_TICKSIZE);
      double tickValue = MarketInfo(name, MODE_TICKVALUE);
      if(contract <= 0 || tickSize <= 0) continue;
      if(fxContract <= 0 && StringFind(name, "GOLD") < 0 && StringFind(name, "XAU") < 0 && StringFind(name, "OIL") < 0 && StringFind(name, "BRENT") < 0)
      {
         fxName = name;
         fxContract = contract;
      }
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

void PlaceLine(string line)
{
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
   string chosen = "";
   string options[];
   int count = StringSplit(parts[2], ',', options);
   for(int i = 0; i < count; i++)
   {
      string candidate = options[i];
      StringTrimLeft(candidate);
      StringTrimRight(candidate);
      if(UseSymbol(candidate)) { chosen = candidate; break; }
   }
   if(chosen == "")
   {
      Report(id, "not_placed", 0, 0, 0, "", "None of the symbol names are on this platform.");
      LastNote = "No symbol for order " + id + ". Cash oil and Brent need MT5.";
      return;
   }
   int spread = (int)MarketInfo(chosen, MODE_SPREAD);
   int digits = (int)MarketInfo(chosen, MODE_DIGITS);
   int maxSpread = MaxSpreadPoints;
   if(MaxSpreadPoints > 0 && (digits <= 2 || StringFind(chosen, "GOLD") >= 0 || StringFind(chosen, "XAU") >= 0 || StringFind(chosen, "SILVER") >= 0 || StringFind(chosen, "XAG") >= 0 || StringFind(chosen, "OIL") >= 0 || StringFind(chosen, "BRENT") >= 0 || StringFind(chosen, "US30") >= 0 || StringFind(chosen, "US100") >= 0 || StringFind(chosen, "US500") >= 0 || StringFind(chosen, "GER40") >= 0 || StringFind(chosen, "JP225") >= 0 || StringFind(chosen, "VOLX") >= 0 || StringFind(chosen, "VIX") >= 0))
   {
      maxSpread = MaxSpreadPoints * 15;
   }
   if(MaxSpreadPoints > 0 && spread > maxSpread)
   {
      Report(id, "not_placed", 0, 0, 0, chosen, "Spread is wider than the copier allows.");
      return;
   }
   lots = FitLots(chosen, lots);
   if(lots <= 0)
   {
      Report(id, "not_placed", 0, 0, 0, chosen, "The size is below this symbol's minimum.");
      return;
   }
   RefreshRates();
   double price = (side == "buy") ? MarketInfo(chosen, MODE_ASK) : MarketInfo(chosen, MODE_BID);
   if(chase > 0 && MathAbs(price - entry) > chase)
   {
      Report(id, "not_placed", 0, price, lots, chosen, "Price moved away from the signal.");
      LastNote = chosen + " moved away from the signal.";
      return;
   }
   double point = MarketInfo(chosen, MODE_POINT);
   double slDist = MathAbs(entry - sl);
   double tpDist = slDist; // Exact distance as stop loss (1:1 Risk-to-Reward)
   double final_sl = (side == "buy") ? (price - slDist) : (price + slDist);
   double final_tp = (side == "buy") ? (price + tpDist) : (price - tpDist);
   double minDist = MarketInfo(chosen, MODE_STOPLEVEL) * point;
   if(minDist > 0 && (MathAbs(price - final_sl) < minDist || MathAbs(price - final_tp) < minDist))
   {
      Report(id, "not_placed", 0, price, lots, chosen, "Stop or target is closer than the broker allows.");
      return;
   }
   int cmd = (side == "buy") ? OP_BUY : OP_SELL;
   int ticket = OrderSend(chosen, cmd, lots, NormalizeDouble(price, digits), SlippagePoints, NormalizeDouble(final_sl, digits), NormalizeDouble(final_tp, digits), comment, Magic, 0, clrNONE);
   if(ticket < 0)
   {
      Report(id, "not_placed", 0, price, lots, chosen, "OrderSend error " + IntegerToString(GetLastError()));
      LastNote = chosen + " order was rejected (" + IntegerToString(GetLastError()) + ").";
      return;
   }
   if(OrderSelect(ticket, SELECT_BY_TICKET, MODE_TRADES))
      Report(id, "placed", ticket, OrderOpenPrice(), OrderLots(), chosen, "filled");
   else
      Report(id, "placed", ticket, price, lots, chosen, "filled");
   LastNote = chosen + " " + side + " filled, ticket " + IntegerToString(ticket) + ".";
}

void CheckBreakEven()
{
   if(BreakEvenProfitUSD <= 0) return;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      if(!OrderSelect(i, SELECT_BY_POS, MODE_TRADES)) continue;
      if(OrderMagicNumber() != Magic) continue;
      if(OrderProfit() < BreakEvenProfitUSD) continue;

      double openPrice = OrderOpenPrice();
      double currentSL = OrderStopLoss();
      double currentTP = OrderTakeProfit();
      int type = OrderType();
      string sym = OrderSymbol();
      int digits = (int)MarketInfo(sym, MODE_DIGITS);
      double point = MarketInfo(sym, MODE_POINT);
      string comment = OrderComment();
      int ticket = OrderTicket();

      bool needsMove = false;
      if(type == OP_BUY)
      {
         if(currentSL < openPrice - point) needsMove = true;
      }
      else if(type == OP_SELL)
      {
         if(currentSL <= 0 || currentSL > openPrice + point) needsMove = true;
      }

      if(needsMove)
      {
         if(OrderModify(ticket, openPrice, NormalizeDouble(openPrice, digits), NormalizeDouble(currentTP, digits), 0, clrNONE))
         {
            Print("Moved SL to entry for ticket ", ticket, " at profit $", DoubleToString(OrderProfit(), 2));
            LastNote = sym + " #" + IntegerToString(ticket) + ": profit reached $" + DoubleToString(OrderProfit(), 2) + ". SL moved to entry.";
            Paint();
            Report(comment, "sl_to_entry", ticket, openPrice, OrderProfit(), sym, "Profit reached $" + DoubleToString(OrderProfit(), 2) + ". Stop loss moved to entry.");
         }
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
