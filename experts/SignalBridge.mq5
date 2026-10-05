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
#property version   "1.10"
#property description "Places Signal Desk orders on the XM account this terminal is logged into."

input string ApiBase          = "https://YOUR-APP-URL";
input string ApiKey           = "";
input int    PollSeconds      = 10;
input int    Magic            = 56021;
input int    SlippagePoints   = 30;
input int    MaxSpreadPoints  = 40;
input double MaxLots          = 0; // 0 = no extra ceiling. The website max lot still applies.

string LastNote = "Starting.";

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

void OnTimer() { Poll(); }

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
      double contract = SymbolInfoDouble(name, SYMBOL_TRADE_CONTRACT_SIZE);
      double tickSize = SymbolInfoDouble(name, SYMBOL_TRADE_TICK_SIZE);
      double tickValue = SymbolInfoDouble(name, SYMBOL_TRADE_TICK_VALUE);
      if(contract <= 0 || tickSize <= 0) continue;
      if(fxContract <= 0 && (StringFind(name, "USD") >= 0 || StringFind(name, "EUR") >= 0 || StringFind(name, "GBP") >= 0))
      {
         // Prefer a plain FX name over gold or oil for the account-type check.
         if(StringFind(name, "GOLD") < 0 && StringFind(name, "XAU") < 0 && StringFind(name, "OIL") < 0 && StringFind(name, "BRENT") < 0 && StringFind(name, "WTI") < 0)
         {
            fxName = name;
            fxContract = contract;
         }
      }
      specs += "spec=" + name
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

void PlaceLine(const string line)
{
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

   string chosen = "";
   string options[];
   int count = StringSplit(names, ',', options);
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
      LastNote = "No symbol for order " + id + " (" + names + ").";
      return;
   }
   int spread = (int)SymbolInfoInteger(chosen, SYMBOL_SPREAD);
   int digits = (int)SymbolInfoInteger(chosen, SYMBOL_DIGITS);
   int maxSpread = MaxSpreadPoints;
   if(MaxSpreadPoints > 0 && (digits <= 2 || StringFind(chosen, "GOLD") >= 0 || StringFind(chosen, "XAU") >= 0 || StringFind(chosen, "SILVER") >= 0 || StringFind(chosen, "XAG") >= 0 || StringFind(chosen, "OIL") >= 0 || StringFind(chosen, "BRENT") >= 0 || StringFind(chosen, "US30") >= 0 || StringFind(chosen, "US100") >= 0 || StringFind(chosen, "US500") >= 0 || StringFind(chosen, "GER40") >= 0 || StringFind(chosen, "JP225") >= 0 || StringFind(chosen, "VOLX") >= 0 || StringFind(chosen, "VIX") >= 0))
   {
      maxSpread = MaxSpreadPoints * 15;
   }
   if(MaxSpreadPoints > 0 && spread > maxSpread)
   {
      Report(id, "not_placed", 0, 0, 0, chosen, "Spread is wider than the copier allows.");
      LastNote = chosen + " spread is " + IntegerToString(spread) + " points.";
      return;
   }
   lots = FitLots(chosen, lots);
   if(lots <= 0)
   {
      Report(id, "not_placed", 0, 0, 0, chosen, "The size is below this symbol's minimum.");
      LastNote = "Size too small on " + chosen + ".";
      return;
   }
   double price = (side == "buy") ? SymbolInfoDouble(chosen, SYMBOL_ASK) : SymbolInfoDouble(chosen, SYMBOL_BID);
   if(chase > 0 && MathAbs(price - entry) > chase)
   {
      Report(id, "not_placed", 0, price, lots, chosen, "Price moved away from the signal.");
      LastNote = chosen + " moved away from the signal. Not chasing.";
      return;
   }
   double point = SymbolInfoDouble(chosen, SYMBOL_POINT);
   double slDist = MathAbs(entry - sl);
   double tpDist = MathAbs(entry - tp);
   double final_sl = (side == "buy") ? (price - slDist) : (price + slDist);
   double final_tp = (side == "buy") ? (price + tpDist) : (price - tpDist);

   int stops = (int)SymbolInfoInteger(chosen, SYMBOL_TRADE_STOPS_LEVEL);
   double minDist = stops * point;
   if(minDist > 0 && (MathAbs(price - final_sl) < minDist || MathAbs(price - final_tp) < minDist))
   {
      Report(id, "not_placed", 0, price, lots, chosen, "Stop or target is closer than the broker allows.");
      LastNote = chosen + " rejected the stop distance.";
      return;
   }
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
   req.tp = NormalizeDouble(final_tp, digits);
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
   Report(id, "placed", res.order, res.price > 0 ? res.price : price, res.volume > 0 ? res.volume : lots, chosen, "filled");
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
