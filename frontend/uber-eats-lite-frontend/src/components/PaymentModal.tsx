import React, { useState } from "react";
import { loadStripe } from "@stripe/stripe-js";
import { Elements, CardElement, useStripe, useElements } from "@stripe/react-stripe-js";
import { Modal } from "./Modal";
import { Button } from "./Button";

const stripePromise = loadStripe(import.meta.env.VITE_STRIPE_PUBLIC_KEY!);
const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8008";

interface PaymentModalProps {
  show: boolean;
  onClose: () => void;
  orderId: string;
  amount: number;
}

function decodeJWT(token: string) {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return payload.sub || "anonymous";
  } catch {
    return "anonymous";
  }
}

const CheckoutForm: React.FC<PaymentModalProps> = ({ show, onClose, orderId, amount }) => {
  const stripe = useStripe();
  const elements = useElements();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const token = localStorage.getItem("token");
  const user_id = token ? decodeJWT(token) : "anonymous";

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!stripe || !elements || !token) return;

    setLoading(true);
    setError("");

    try {
      const res = await fetch(`${API_BASE_URL}/payments/create-intent`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
          order_id: orderId,
          user_id,
          amount,
        }),
      });

      if (!res.ok) {
        const text = await res.text();
        throw new Error(`Server responded with ${res.status}: ${text}`);
      }

      const data = await res.json();
      const clientSecret = data.client_secret;
      if (!clientSecret) throw new Error("Missing client_secret");

      const result = await stripe.confirmCardPayment(clientSecret, {
        payment_method: { card: elements.getElement(CardElement)! },
      });

      if (result.error) {
        setError(result.error.message || "Payment failed");
      } else if (result.paymentIntent?.status === "succeeded") {
        alert("✅ Payment successful!");
        onClose();
      }
    } catch (err: any) {
      console.error("[Payment Error]", err);
      setError(err.message || "Something went wrong");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Modal show={show} onClose={onClose} title="Confirm Payment">
      <form onSubmit={handleSubmit} className="space-y-4">
        <p className="text-gray-700">
          Pay <strong>${amount.toFixed(2)}</strong> for order <code>{orderId}</code>
        </p>

        <div className="border rounded-md p-2">
          <CardElement options={{ style: { base: { fontSize: "16px" } } }} />
        </div>

        {error && <p className="text-red-600 text-sm">{error}</p>}

        <Button type="submit" loading={loading}>
          Confirm Payment
        </Button>
      </form>
    </Modal>
  );
};

export const PaymentModal: React.FC<PaymentModalProps> = (props) => (
  <Elements stripe={stripePromise}>
    <CheckoutForm {...props} />
  </Elements>
);
