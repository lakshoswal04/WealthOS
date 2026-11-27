/**
 * The trading clients, one module per area (see lib/clients/). This barrel
 * keeps a single import path for components and offers `trade`, the flat
 * client older components use.
 */

import { account } from "./clients/account";
import { autopilot } from "./clients/autopilot";
import { chat } from "./clients/chat";
import { market } from "./clients/market";
import { options } from "./clients/options";
import { paper } from "./clients/paper";
import { research } from "./clients/research";
import { ideas, screeners } from "./clients/screeners";
import { signals } from "./clients/signals";

export * from "./clients/types";
export { unavailableFrom, type Unavailable } from "./clients/http";
export { account, autopilot, chat, ideas, market, options, paper, research, screeners, signals };

export const trade = {
  marketStatus: market.status, indices: market.indices, quote: market.quote, quotes: market.quotes,
  movers: market.movers, candles: market.candles, search: market.search, universe: market.universe,
  expiries: options.expiries, chain: options.chain, optionSummary: options.summary,
  multiStrike: options.multiStrike, topContracts: options.top, heatmap: options.heatmap, optionCandles: options.candles,
  screens: screeners.list, runScreen: screeners.run, runCustom: screeners.runCustom, savedScreens: screeners.saved,
  saveScreen: screeners.save, runSaved: screeners.runSaved, deleteSaved: screeners.deleteSaved,
  recommendations: ideas.recommendations, strategies: ideas.strategies, backtest: ideas.backtest,
  paperPortfolio: paper.portfolio, paperOrders: paper.orders, placeOrder: paper.place, cancelOrder: paper.cancel,
  resetPaper: paper.reset, autopilotPreview: paper.autopilotPreview, autopilot: paper.autopilot,
  threads: chat.threads, thread: chat.thread, newThread: chat.create, send: chat.send, deleteThread: chat.remove,
};
