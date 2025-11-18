// src/components/OrderModal.tsx
import { Button } from "../components/Button";
import type { OrderStatus } from "./types";

export interface OrderForm {
  user_id: string;
  items: string[];
  driver_id: string;
  status: OrderStatus;
}

interface Props {
  show: boolean;
  onClose: () => void;
  form: OrderForm;
  setForm: React.Dispatch<React.SetStateAction<OrderForm>>;
  onSubmit: () => void;
  loading: boolean;
  editingId: string | null;
  isAdmin: boolean;
}

const MENU_ITEMS = [
  { name: "Burger", price: 8 },
  { name: "Fries", price: 4 },
  { name: "Coke", price: 3 },
  { name: "Pizza", price: 12 },
  { name: "Salad", price: 6 },
];

export default function OrderModal({
  show,
  onClose,
  form,
  setForm,
  onSubmit,
  loading,
  editingId,
  isAdmin,
}: Props) {
  if (!show) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black opacity-50"
        onClick={onClose}
      />

      {/* Modal content */}
      <div className="relative bg-white rounded-lg p-6 w-full max-w-md z-10 shadow-lg">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-2 right-2 text-gray-500 hover:text-gray-700"
        >
          ✖
        </button>

        <h2 className="text-xl font-bold mb-4">
          {editingId ? "Edit Order" : "Create Order"}
        </h2>

        {/* User ID input */}
        <input
          type="text"
          placeholder="User ID"
          value={form.user_id}
          onChange={(e) => setForm({ ...form, user_id: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
          disabled={!isAdmin}
        />

        {/* Menu items */}
        <div className="grid grid-cols-2 gap-2 mb-3">
          {MENU_ITEMS.map((item) => (
            <button
              key={item.name}
              type="button"
              onClick={() =>
                setForm((prev) => ({
                  ...prev,
                  items: prev.items.includes(item.name)
                    ? prev.items.filter((i) => i !== item.name)
                    : [...prev.items, item.name],
                }))
              }
              className={`border rounded p-2 text-sm transition-colors ${
                form.items.includes(item.name)
                  ? "bg-green-500 text-white"
                  : "bg-gray-100 hover:bg-gray-200"
              }`}
            >
              {item.name} – ${item.price}
            </button>
          ))}
        </div>

        {/* Submit button */}
        <Button
          onClick={onSubmit}
          loading={loading}
          className="w-full"
        >
          {editingId ? "Update Order" : "Create Order"}
        </Button>
      </div>
    </div>
  );
}
