import { V1, post, request } from "./http";
import type { AutopilotBasket, OrderRequest, PaperOrder, PaperPortfolio } from "./types";

export const paper = {
  portfolio: () => request<PaperPortfolio>(`${V1}/paper/portfolio`),
  orders: () => request<{ orders: PaperOrder[]; total: number }>(`${V1}/paper/orders`),
  place: (order: OrderRequest) => post<PaperOrder>(`${V1}/paper/orders`, order),
  cancel: (id: number) => post<PaperOrder>(`${V1}/paper/orders/${id}/cancel`, {}),
  reset: () => post<{ cash: number }>(`${V1}/paper/reset`, {}),
  autopilotPreview: (amount: number) => post<AutopilotBasket>(`${V1}/paper/autopilot/preview`, { amount }),
  autopilot: (basket: { symbol: string; quantity: number }[], amount?: number) =>
    post<{ orders: PaperOrder[] }>(`${V1}/paper/autopilot`, { basket, amount }),
};
