import { useState } from "react";
import { useNavigate } from "react-router-dom";

interface LoginProps {
  onLogin: (token: string) => void; // pass token to parent
}

export default function Login({ onLogin }: LoginProps) {
  const [email, setEmail] = useState<string>("admin@demo.com"); // demo admin
  const [password, setPassword] = useState<string>("admin123");  // demo admin
  const navigate = useNavigate();

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    try {
      const res = await fetch("http://localhost:8000/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, password }),
      });

      const data: { success: boolean; message?: string; data?: { token: string } } =
        await res.json();

      if (data.success && data.data?.token) {
        const token = data.data.token;
        localStorage.setItem("token", token);
        onLogin(token);

        // decode JWT to get role
        const payload = JSON.parse(atob(token.split(".")[1]));
        const role = payload.role;

        // redirect based on role
        if (role === "admin") {
          navigate("/users"); // admin dashboard
        } else if (role === "driver") {
          navigate("/driver/orders");
        } else {
          navigate("/orders"); // regular user
        }
      } else {
        alert(data.message || "Login failed");
      }
    } catch (err) {
      console.error("Login error:", err);
      alert("Login failed. Please try again.");
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="max-w-sm mx-auto mt-10 p-4 border rounded shadow"
    >
      <h2 className="text-xl font-bold mb-4">Login</h2>
      <input
        type="email"
        placeholder="Email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        className="mb-2 p-2 w-full border rounded"
        required
      />
      <input
        type="password"
        placeholder="Password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        className="mb-2 p-2 w-full border rounded"
        required
      />
      <button
        type="submit"
        className="bg-blue-500 text-white p-2 rounded w-full hover:bg-blue-600"
      >
        Login
      </button>
    </form>
  );
}
