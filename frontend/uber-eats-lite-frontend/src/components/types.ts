export type OrderStatus = "pending" | "paid" | "assigned" | "delivered";

export interface Order {
  id: string;
  user_id: string;
  user_name?: string;
  items: string[];
  total: number;
  status: OrderStatus;
  driver_id?: string | null;
  payment_status?: string;
  assigning?: boolean;
  [k: string]: any;
}
