// Signal Desk copier for MetaTrader 5.
// Keep symbol names in step with backend/app/symbols.py.
//
// Setup:
// 1. Copy this file into MQL5/Experts and compile it.
// 2. Tools → Options → Expert Advisors → allow algorithmic trading.
// 3. Allow WebRequest for your desk URL (the site origin, no path).
// 4. Attach this to any chart. Paste ApiBase and the copier key.
// Orders are sent only when the website account is set to automatic.

#property copyright "Signal Desk"
#property version   "1.11"
#property description "Places Signal Desk orders on the XM account this terminal is logged into."

input string ApiBase          = "https://fx.veespatial.com";
input string ApiKey           = "";
input int    PollSeconds      = 10;
input int    Magic            = 56021;
input int    SlippagePoints   = 30;
input int    MaxSpreadPoints  = 40;
input double MaxLots          = 0; // 0 = no extra ceiling. The website max lot still applies.
input double BreakEvenProfitUSD = 0; //0.4 Floating profit that moves the stop to the entry price. 0 = off.
input double LockProfitTriggerUSD = 0; //0.5 Floating profit that locks a winner. 0 = off.
input double LockProfitUSD = 1.0; // Profit the stop locks in once the trigger is reached.
input double SpreadWidenRatio = 0.15; // When the spread is this fraction of the stop, push the stop out by the spread.

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

bool Http(const string method, const string path, const string body, string &response, int &code)
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
      LastNote = "WebRequest was blocked (error " + IntegerToString(GetLastError()) + "). Allow this URL in Tools → Options → Expert Advisors:\n" + BaseUrl();
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

bool UseSymbol(const string name)
{
   if(StringLen(name) < 2) return false;
   if(!SymbolSelect(name, true)) return false;
   long mode = SymbolInfoInteger(name, SYMBOL_TRADE_MODE);
   if(mode == SYMBOL_TRADE_MODE_DISABLED) return false;
   return (SymbolInfoDouble(name, SYMBOL_ASK) > 0 || SymbolInfoDouble(name, SYMBOL_BID) > 0);
}

bool PrefixMatch(const string symbol, const string alias)
{
   if(StringLen(alias) < 4) return false;
   if(StringFind(symbol, alias) != 0) return false;
   if(StringLen(symbol) == StringLen(alias)) return true;
   ushort ch = StringGetCharacter(symbol, StringLen(alias));
   return (ch == '#' || ch == '.' || ch == '-' || ch == '_');
}

bool IsAnchoredMarket(const string name)
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

int ExpiryKey(const string sym)
{
   string months[12] = {"JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"};
   int n = StringLen(sym);
   for(int m = 0; m < 12; m++)
   {
      int pos = StringFind(sym, months[m]);
      if(pos < 0 || pos + 5 > n) continue;
      int year = (int)StringToInteger(StringSubstr(sym, pos + 3, 2));
      if(year <= 0) continue;
      return (2000 + year) * 100 + (m + 1);
   }
   return 999999;
}

string FindRootSymbol(const string root)
{
   string best = "";
   int bestKey = 999999;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int nowKey = dt.year * 100 + dt.mon;
   for(int pass = 0; pass < 2; pass++)
   {
      bool selectedOnly = (pass == 0);
      int total = SymbolsTotal(selectedOnly);
      for(int i = 0; i < total; i++)
      {
         string sym = SymbolName(i, selectedOnly);
         if(sym != root && !PrefixMatch(sym, root)) continue;
         if(StringFind(sym, "Cash") >= 0)
         {
            if(UseSymbol(sym)) return sym;
            continue;
         }
         int key = ExpiryKey(sym);
         if(key < nowKey) continue;
         if(key < bestKey)
         {
            bestKey = key;
            best = sym;
         }
      }
      if(best != "" && UseSymbol(best)) return best;
      best = "";
      bestKey = 999999;
   }
   return "";
}

string ResolveSymbol(const string names, const double entry)
{
   string options[];
   int count = StringSplit(names, ',', options);
   string exact = "";
   string exactCash = "";
   for(int i = 0; i < count; i++)
   {
      string candidate = options[i];
      StringTrimLeft(candidate);
      StringTrimRight(candidate);
      if(candidate == "" || !UseSymbol(candidate)) continue;
      if(exact == "") exact = candidate;
      if(exactCash == "" && StringFind(candidate, "Cash") >= 0) exactCash = candidate;
   }
   if(exactCash != "") return exactCash;
   if(exact != "") return exact;

   string best = "";
   double bestScore = 1e100;
   MqlDateTime dt;
   TimeToStruct(TimeCurrent(), dt);
   int nowKey = dt.year * 100 + dt.mon;
   for(int pass = 0; pass < 2 && best == ""; pass++)
   {
      bool selectedOnly = (pass == 0);
      int total = SymbolsTotal(selectedOnly);
      for(int i = 0; i < total; i++)
      {
         string sym = SymbolName(i, selectedOnly);
         bool hit = false;
         for(int a = 0; a < count; a++)
         {
            string alias = options[a];
            StringTrimLeft(alias);
            StringTrimRight(alias);
            if(alias != "" && (sym == alias || PrefixMatch(sym, alias))) { hit = true; break; }
         }
         if(!hit) continue;
         if(StringFind(sym, "Cash") >= 0 && UseSymbol(sym)) return sym;
         int key = ExpiryKey(sym);
         if(key < nowKey) continue;
         double bid = SymbolInfoDouble(sym, SYMBOL_BID);
         double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
         double mid = (bid > 0 && ask > 0) ? (bid + ask) / 2.0 : (bid > 0 ? bid : ask);
         double score = (double)key;
         if(mid > 0 && entry > 0)
         {
            double ratio = mid / entry;
            if(ratio < 1.0) ratio = 1.0 / ratio;
            while(ratio > 5.0) ratio /= 10.0;
            while(ratio < 0.2) ratio *= 10.0;
            score = MathAbs(MathLog10(ratio));
         }
         if(score < bestScore)
         {
            bestScore = score;
            best = sym;
         }
      }
   }
   if(best != "" && UseSymbol(best)) return best;
   return "";
}

double QuoteScale(const double signalPrice, const double brokerPrice)
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

string DigitsOnly(const string text)
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

string SpecLine(const string name)
{
   double contract = SymbolInfoDouble(name, SYMBOL_TRADE_CONTRACT_SIZE);
   double tickSize = SymbolInfoDouble(name, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(name, SYMBOL_TRADE_TICK_VALUE);
   if(contract <= 0 || tickSize <= 0) return "";
   return "spec=" + name
      + "|" + DoubleToString(contract, 2)
      + "|" + DoubleToString(tickSize, 8)
      + "|" + DoubleToString(tickValue, 6)
      + "|" + DoubleToString(SymbolInfoDouble(name, SYMBOL_VOLUME_MIN), 2)
      + "|" + DoubleToString(SymbolInfoDouble(name, SYMBOL_VOLUME_MAX), 2)
      + "|" + DoubleToString(SymbolInfoDouble(name, SYMBOL_VOLUME_STEP), 2)
      + "|" + IntegerToString((int)SymbolInfoInteger(name, SYMBOL_DIGITS))
      + "|" + DoubleToString(SymbolInfoDouble(name, SYMBOL_BID), (int)SymbolInfoInteger(name, SYMBOL_DIGITS))
      + "|" + DoubleToString(SymbolInfoDouble(name, SYMBOL_ASK), (int)SymbolInfoInteger(name, SYMBOL_DIGITS))
      + "\n";
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
      "OILCash","OILCash#","OILCash.m","USOIL","WTI","WTIOILCash","XTIUSD",
      "BRENTCash","BRENTCash#","BRENTCash.m","UKOIL","XBRUSD",
      "HGCOP","HGCOP#","COPPER","COPPER#","COPPERCash","COPPERCash#","HGCOPPER",
      "NGASCash","NGASCash#","NATGASCash","NGAS","NGAS#","NATGAS","NGAS.c",
      "SBEAN","SBEAN#","SOYBEAN","SOYBEAN#","SOYBEANCash","SOYBEANCash#","SOY",
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
      string line = SpecLine(name);
      if(line == "") continue;
      double contract = SymbolInfoDouble(name, SYMBOL_TRADE_CONTRACT_SIZE);
      if(fxContract <= 0 && (StringFind(name, "USD") >= 0 || StringFind(name, "EUR") >= 0 || StringFind(name, "GBP") >= 0))
      {
         // Prefer a plain FX name over gold or oil for the account-type check.
         if(StringFind(name, "GOLD") < 0 && StringFind(name, "XAU") < 0 && StringFind(name, "OIL") < 0 && StringFind(name, "BRENT") < 0 && StringFind(name, "WTI") < 0)
         {
            fxName = name;
            fxContract = contract;
         }
      }
      specs += line;
   }
   string roots[] = {"OILCash","BRENTCash","NGASCash","HGCOP","SBEAN","COPPER","SOYBEAN","GOLD","SILVER"};
   for(int r = 0; r < ArraySize(roots); r++)
   {
      if(StringFind(specs, "spec=" + roots[r] + "|") >= 0) continue;
      if(StringFind(specs, "spec=" + roots[r] + "#") >= 0) continue;
      if(StringFind(specs, "spec=" + roots[r] + "-") >= 0) continue;
      if(StringFind(specs, "spec=" + roots[r] + ".") >= 0) continue;
      string found = FindRootSymbol(roots[r]);
      if(found == "" || StringFind(specs, "spec=" + found + "|") >= 0) continue;
      specs += SpecLine(found);
   }
   return "platform=mt5\n"
      + "login=" + IntegerToString(AccountInfoInteger(ACCOUNT_LOGIN)) + "\n"
      + "broker=" + AccountInfoString(ACCOUNT_SERVER) + "\n"
      + "balance=" + DoubleToString(AccountInfoDouble(ACCOUNT_BALANCE), 2) + "\n"
      + "equity=" + DoubleToString(AccountInfoDouble(ACCOUNT_EQUITY), 2) + "\n"
      + "currency=" + AccountInfoString(ACCOUNT_CURRENCY) + "\n"
      + "fx_contract=" + DoubleToString(fxContract, 2) + "\n"
      + "fx_symbol=" + fxName + "\n"
      + specs;
}

void Report(const string id, const string status, const ulong ticket, const double price, const double lots, const string symbol, const string message)
{
   string body = "delivery_id=" + id + "\n"
      + "status=" + status + "\n"
      + "ticket=" + (ticket > 0 ? IntegerToString((int)ticket) : "") + "\n"
      + "fill_price=" + DoubleToString(price, 8) + "\n"
      + "lots=" + DoubleToString(lots, 2) + "\n"
      + "broker_symbol=" + symbol + "\n"
      + "message=" + message + "\n";
   string response;
   int code;
   Http("POST", "/api/ea/executions", body, response, code);
}

string ProcessedIds[];

bool IsDeliveryProcessed(const string id)
{
   string name = "SB_Delivery_" + id;
   if(GlobalVariableCheck(name)) return true;
   int total = ArraySize(ProcessedIds);
   for(int i = 0; i < total; i++)
   {
      if(ProcessedIds[i] == id) return true;
   }
   return false;
}

void MarkDeliveryProcessed(const string id)
{
   string name = "SB_Delivery_" + id;
   GlobalVariableSet(name, (double)TimeCurrent());
   if(IsDeliveryProcessed(id)) return;
   int total = ArraySize(ProcessedIds);
   ArrayResize(ProcessedIds, total + 1);
   ProcessedIds[total] = id;
}

bool FindPosition(const string comment, ulong &ticket, double &price, double &lots, string &symbol)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if((int)PositionGetInteger(POSITION_MAGIC) != Magic) continue;
      string posComment = PositionGetString(POSITION_COMMENT);
      if(posComment != comment && StringFind(posComment, comment) < 0) continue;
      ticket = t;
      price = PositionGetDouble(POSITION_PRICE_OPEN);
      lots = PositionGetDouble(POSITION_VOLUME);
      symbol = PositionGetString(POSITION_SYMBOL);
      return true;
   }
   return false;
}

ENUM_ORDER_TYPE_FILLING Filling(const string symbol)
{
   long mode = SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   if((mode & SYMBOL_FILLING_IOC) == SYMBOL_FILLING_IOC) return ORDER_FILLING_IOC;
   if((mode & SYMBOL_FILLING_FOK) == SYMBOL_FILLING_FOK) return ORDER_FILLING_FOK;
   return ORDER_FILLING_RETURN;
}

double FitLots(const string symbol, double lots)
{
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   double minv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double maxv = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0) step = 0.01;
   lots = MathFloor(lots / step + 1e-8) * step;
   lots = NormalizeDouble(lots, 2);
   if(lots + 1e-8 < minv) return 0;
   if(maxv > 0 && lots > maxv) lots = maxv;
   return lots;
}

double MoneyToPrice(const string sym, const double volume, const double money)
{
   double tickSize = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE);
   double tickValue = SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE);
   if(tickSize <= 0 || tickValue <= 0 || volume <= 0 || money <= 0) return 0;
   return money * tickSize / (tickValue * volume);
}

double RoomForStop(const string sym, const long type, const double market)
{
   double point = SymbolInfoDouble(sym, SYMBOL_POINT);
   int stops = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_STOPS_LEVEL);
   int freeze = (int)SymbolInfoInteger(sym, SYMBOL_TRADE_FREEZE_LEVEL);
   double need = MathMax(stops, freeze) * point;
   double spread = SymbolInfoDouble(sym, SYMBOL_ASK) - SymbolInfoDouble(sym, SYMBOL_BID);
   if(spread < 0) spread = 0;
   if(need < spread) need = spread;
   if(need < point) need = point;
   return (type == POSITION_TYPE_BUY) ? market - need : market + need;
}

void CheckBreakEven()
{
   if(BreakEvenProfitUSD <= 0 && LockProfitTriggerUSD <= 0) return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || !PositionSelectByTicket(ticket)) continue;
      if((int)PositionGetInteger(POSITION_MAGIC) != Magic) continue;

      double profit = PositionGetDouble(POSITION_PROFIT);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSL = PositionGetDouble(POSITION_SL);
      double currentTP = PositionGetDouble(POSITION_TP);
      long type = PositionGetInteger(POSITION_TYPE);
      string sym = PositionGetString(POSITION_SYMBOL);
      int digits = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
      double point = SymbolInfoDouble(sym, SYMBOL_POINT);
      double volume = PositionGetDouble(POSITION_VOLUME);
      string comment = PositionGetString(POSITION_COMMENT);
      double bid = SymbolInfoDouble(sym, SYMBOL_BID);
      double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
      if(bid <= 0 || ask <= 0) continue;

      string status = "";
      string message = "";
      double targetSL = 0;
      if(LockProfitTriggerUSD > 0 && LockProfitUSD > 0 && profit + 1e-8 >= LockProfitTriggerUSD)
      {
         double lockDist = MoneyToPrice(sym, volume, LockProfitUSD);
         if(lockDist <= 0) continue;
         targetSL = (type == POSITION_TYPE_BUY) ? openPrice + lockDist : openPrice - lockDist;
         status = "sl_lock";
         message = sym + " #" + IntegerToString((int)ticket) + ": profit $" + DoubleToString(profit, 2)
            + ". SL moved to lock $" + DoubleToString(LockProfitUSD, 2) + ".";
      }
      else if(BreakEvenProfitUSD > 0 && profit + 1e-8 >= BreakEvenProfitUSD)
      {
         targetSL = openPrice;
         status = "sl_to_entry";
         message = sym + " #" + IntegerToString((int)ticket) + ": profit $" + DoubleToString(profit, 2) + ". SL moved to entry.";
      }
      else continue;

      double market = (type == POSITION_TYPE_BUY) ? bid : ask;
      double spread = ask - bid;
      double cushion = (type == POSITION_TYPE_BUY) ? (market - targetSL) : (targetSL - market);
      // A wide bid-ask gap would tag a stop that sits inside it. Keep the
      // planned room outside that gap instead of tightening into it.
      if(SpreadWidenRatio > 0 && spread > 0 && cushion > 0 && spread > cushion * SpreadWidenRatio)
      {
         if(type == POSITION_TYPE_BUY) targetSL = MathMin(targetSL, market - spread);
         else targetSL = MathMax(targetSL, market + spread);
      }
      double limit = RoomForStop(sym, type, market);
      if(type == POSITION_TYPE_BUY)
      {
         if(targetSL > limit) targetSL = limit;
         if(targetSL <= 0 || targetSL >= market) continue;
         if(currentSL > 0 && targetSL <= currentSL + point) continue;
      }
      else
      {
         if(targetSL < limit) targetSL = limit;
         if(targetSL <= market) continue;
         if(currentSL > 0 && targetSL >= currentSL - point) continue;
      }

      MqlTradeRequest req;
      MqlTradeResult res;
      ZeroMemory(req);
      ZeroMemory(res);
      req.action = TRADE_ACTION_SLTP;
      req.position = ticket;
      req.symbol = sym;
      req.sl = NormalizeDouble(targetSL, digits);
      req.tp = NormalizeDouble(currentTP, digits);
      if(OrderSend(req, res) && (res.retcode == TRADE_RETCODE_DONE || res.retcode == TRADE_RETCODE_DONE_PARTIAL))
      {
         Print(message);
         LastNote = message;
         Paint();
         Report(DigitsOnly(comment), status, ticket, req.sl, profit, sym, message);
      }
   }
}

bool CommentMatches(const string posComment, const string comment)
{
   if(StringFind(posComment, comment) != 0) return false;
   int next = StringLen(comment);
   if(StringLen(posComment) == next) return true;
   int ch = StringGetCharacter(posComment, next);
   return (ch < '0' || ch > '9');
}

void CloseLine(const string id, const string comment)
{
   ulong ticket = 0;
   double price = 0, lots = 0;
   string symbol = "";
   bool found = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong t = PositionGetTicket(i);
      if(t == 0 || !PositionSelectByTicket(t)) continue;
      if((int)PositionGetInteger(POSITION_MAGIC) != Magic) continue;
      if(!CommentMatches(PositionGetString(POSITION_COMMENT), comment)) continue;
      ticket = t;
      price = PositionGetDouble(POSITION_PRICE_OPEN);
      lots = PositionGetDouble(POSITION_VOLUME);
      symbol = PositionGetString(POSITION_SYMBOL);
      found = true;
      break;
   }
   if(!found)
   {
      Report(id, "closed", 0, 0, 0, "", "already flat");
      LastNote = comment + " is already flat.";
      return;
   }
   if(!PositionSelectByTicket(ticket)) return;
   string sym = PositionGetString(POSITION_SYMBOL);
   long type = PositionGetInteger(POSITION_TYPE);
   double volume = PositionGetDouble(POSITION_VOLUME);
   double bid = SymbolInfoDouble(sym, SYMBOL_BID);
   double ask = SymbolInfoDouble(sym, SYMBOL_ASK);
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action = TRADE_ACTION_DEAL;
   req.position = ticket;
   req.symbol = sym;
   req.volume = volume;
   req.type = (type == POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
   req.price = (type == POSITION_TYPE_BUY) ? bid : ask;
   req.deviation = SlippagePoints;
   req.magic = Magic;
   req.comment = comment;
   req.type_filling = Filling(sym);
   req.type_time = ORDER_TIME_GTC;
   if(!OrderSend(req, res) || (res.retcode != TRADE_RETCODE_DONE && res.retcode != TRADE_RETCODE_DONE_PARTIAL))
   {
      LastNote = sym + " close was rejected (" + IntegerToString((int)res.retcode) + ").";
      return;
   }
   double fill = res.price > 0 ? res.price : req.price;
   Report(id, "closed", ticket, fill, volume, sym, "closed on the opposite ICWR signal");
   LastNote = sym + " closed, ticket " + IntegerToString((int)ticket) + ".";
}

void PlaceLine(const string line)
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
   string names = parts[2];
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

   if(IsDeliveryProcessed(id))
   {
      LastNote = "Order " + id + " already processed, skipping duplicate.";
      return;
   }

   ulong existing = 0;
   double openPrice = 0, openLots = 0;
   string openSymbol = "";
   if(FindPosition(comment, existing, openPrice, openLots, openSymbol))
   {
      MarkDeliveryProcessed(id);
      Report(id, "placed", existing, openPrice, openLots, openSymbol, "already open");
      LastNote = comment + " is already open, ticket " + IntegerToString((int)existing) + ".";
      return;
   }
   if(!TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) || !MQLInfoInteger(MQL_TRADE_ALLOWED) || !AccountInfoInteger(ACCOUNT_TRADE_ALLOWED))
   {
      Report(id, "not_placed", 0, 0, 0, "", "AutoTrading is turned off in the terminal.");
      LastNote = "AutoTrading is off. Turn on the green button in the toolbar.";
      return;
   }
   if(MaxLots > 0 && lots > MaxLots + 1e-8)
   {
      Report(id, "not_placed", 0, 0, lots, "", "Above the MaxLots ceiling on this chart.");
      LastNote = "Order " + id + " is above MaxLots.";
      return;
   }

   string chosen = ResolveSymbol(names, entry);
   if(chosen == "")
   {
      Report(id, "not_placed", 0, 0, 0, "", "None of the symbol names are on this platform.");
      LastNote = "No symbol for order " + id + " (" + names + ").";
      return;
   }
   bool anchored = IsAnchoredMarket(chosen);
   int spread = (int)SymbolInfoInteger(chosen, SYMBOL_SPREAD);
   int digits = (int)SymbolInfoInteger(chosen, SYMBOL_DIGITS);
   double bid = SymbolInfoDouble(chosen, SYMBOL_BID);
   double ask = SymbolInfoDouble(chosen, SYMBOL_ASK);
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
         LastNote = chosen + " spread is " + IntegerToString(spread) + " points.";
         return;
      }
   }
   lots = FitLots(chosen, lots);
   if(lots <= 0)
   {
      Report(id, "not_placed", 0, 0, 0, chosen, "The size is below this symbol's minimum.");
      LastNote = "Size too small on " + chosen + ".";
      return;
   }
   double price = (side == "buy") ? ask : bid;
   if(anchored && price > 0 && spreadPrice > price * 0.08)
   {
      Report(id, "not_placed", 0, price, lots, chosen, "Spread is too wide to price the stop.");
      LastNote = chosen + " spread is too wide to price the stop.";
      return;
   }
   // Metals and commodities are signaled from Yahoo and filled here.
   // A different cash price is not a reason to skip the trade.
   if(!anchored && chase > 0 && MathAbs(price - entry) > chase)
   {
      Report(id, "not_placed", 0, price, lots, chosen, "Price moved away from the signal.");
      LastNote = chosen + " moved away from the signal. Not chasing.";
      return;
   }
   double point = SymbolInfoDouble(chosen, SYMBOL_POINT);
   double scale = anchored ? QuoteScale(entry, price) : 1.0;
   double slDist = MathAbs(entry - sl) * scale;
   bool noTarget = (tp <= 0.0);
   double tpDist = noTarget ? 0.0 : MathAbs(entry - tp) * scale;
   double planned = slDist;
   if(anchored && SpreadWidenRatio > 0 && planned > 0 && spreadPrice > planned * SpreadWidenRatio)
      slDist += spreadPrice;

   int stops = (int)SymbolInfoInteger(chosen, SYMBOL_TRADE_STOPS_LEVEL);
   double minDist = stops * point;
   if(minDist > 0 && slDist < minDist)
   {
      if(!anchored)
      {
         Report(id, "not_placed", 0, price, lots, chosen, "Stop or target is closer than the broker allows.");
         LastNote = chosen + " rejected the stop distance.";
         return;
      }
      slDist = minDist;
   }
   if(!noTarget && minDist > 0 && tpDist < minDist)
   {
      if(!anchored)
      {
         Report(id, "not_placed", 0, price, lots, chosen, "Stop or target is closer than the broker allows.");
         LastNote = chosen + " rejected the stop distance.";
         return;
      }
      tpDist = minDist;
   }
   if(anchored && planned > 0 && slDist > planned)
   {
      double shrunk = FitLots(chosen, lots * planned / slDist);
      if(shrunk > 0) lots = shrunk;
   }
   double final_sl = (side == "buy") ? (price - slDist) : (price + slDist);
   double final_tp = 0.0;
   if(!noTarget)
      final_tp = (side == "buy") ? (price + tpDist) : (price - tpDist);
   string fillNote = (anchored && slDist > planned + point) ? "filled, stop widened for the spread" : "filled";
   MqlTradeRequest req;
   MqlTradeResult res;
   ZeroMemory(req);
   ZeroMemory(res);
   req.action = TRADE_ACTION_DEAL;
   req.symbol = chosen;
   req.volume = lots;
   req.type = (side == "buy") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
   req.price = price;
   req.sl = NormalizeDouble(final_sl, digits);
   req.tp = noTarget ? 0.0 : NormalizeDouble(final_tp, digits);
   req.deviation = SlippagePoints;
   req.magic = Magic;
   req.comment = comment;
   req.type_filling = Filling(chosen);
   req.type_time = ORDER_TIME_GTC;
   if(!OrderSend(req, res) || (res.retcode != TRADE_RETCODE_DONE && res.retcode != TRADE_RETCODE_DONE_PARTIAL))
   {
      Report(id, "not_placed", 0, price, lots, chosen, "OrderSend " + IntegerToString((int)res.retcode));
      LastNote = chosen + " order was rejected (" + IntegerToString((int)res.retcode) + ").";
      return;
   }
   MarkDeliveryProcessed(id);
   Report(id, "placed", res.order, res.price > 0 ? res.price : price, res.volume > 0 ? res.volume : lots, chosen, fillNote);
   LastNote = chosen + " " + side + " filled, ticket " + IntegerToString((int)res.order) + ".";
}

void Poll()
{
   string response;
   int code;
   if(!Http("POST", "/api/ea/heartbeat", Heartbeat(), response, code))
   {
      Paint();
      return;
   }
   if(StringFind(response, "mismatch=1") >= 0)
      LastNote = "Connected, but the account type on the website does not match this platform. Orders are paused.";
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
   if(jobs == 0 && StringFind(response, "mismatch=1") < 0)
      LastNote = "Connected. No order is waiting.";
   Paint();
}
