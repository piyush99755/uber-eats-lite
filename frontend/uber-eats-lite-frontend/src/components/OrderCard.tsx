import { Button } from "../components/Button";
import type { Order } from "./types";

interface Props {
  order: Order;
  onEdit: (order: Order) => void;
  onPay: (order: Order) => void;
  onDelete: (id: string, ownerId?: string) => void;
}

export default function OrderCard({ order, onEdit, onPay, onDelete }: Props) {
  const statusColor = {
    pending: "text-yellow-600",
    paid: "text-blue-600",
    assigned: "text-purple-600",
    delivered: "text-green-600",
  }[order.status];

  return (
    <div className="border rounded-lg p-4 bg-white shadow">
      <p><strong>User:</strong> {order.user_name || order.user_id}</p>
      <p><strong>Items:</strong> {Array.isArray(order.items) ? order.items.join(", ") : ""}</p>
      <p><strong>Total:</strong> ${order.total.toFixed(2)}</p>
      <p>
        <strong>Status:</strong> <span className={`font-semibold ${statusColor}`}>{order.status}</span>
        {order.status === "paid" && !order.driver_id && (
          <span className="ml-3 inline-flex items-center text-sm text-gray-600">
            <svg className="animate-spin -ml-1 mr-2 h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"></path>
            </svg>
            Assigning driver…
          </span>
        )}
      </p>
      <p><strong>Driver:</strong> {order.driver_name ?? order.driver_id ?? "Unassigned"}</p>

      <div className="flex gap-2 mt-3">
        <Button onClick={() => onEdit(order)} disabled={["assigned", "delivered"].includes(order.status)}>✏️ Edit</Button>
        {order.status === "pending" && <Button onClick={() => onPay(order)}>💳 Pay Now</Button>}
        <Button variant="danger" onClick={() => onDelete(order.id, order.user_id)}>🗑 Delete</Button>
      </div>
    </div>
  );
}
