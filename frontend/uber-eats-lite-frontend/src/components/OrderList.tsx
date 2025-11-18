import OrderCard from "./OrderCard";
import type { Order } from "./types";

interface Props {
  orders: Order[];
  onEdit: (order: Order) => void;
  onPay: (order: Order) => void;
  onDelete: (id: string, ownerId?: string) => void;
}

export default function OrderList({ orders, onEdit, onPay, onDelete }: Props) {
  if (!orders.length) return <p>No orders found</p>;

  return (
    <div className="grid gap-3">
      {orders.map((order) => (
        <OrderCard key={order.id} order={order} onEdit={onEdit} onPay={onPay} onDelete={onDelete} />
      ))}
    </div>
  );
}
