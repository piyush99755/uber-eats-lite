import { useState } from "react";

interface SignupProps {
  onSignupSuccess?: () => void; // optional callback after successful signup
}

export default function Signup({ onSignupSuccess }: SignupProps) {
  const [name, setName] = useState<string>("");
  const [email, setEmail] = useState<string>("");
  const [password, setPassword] = useState<string>("");

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    try {
      const res = await fetch("http://localhost:8000/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, email, password }),
      });

      const data: { success: boolean; message?: string } = await res.json();

      if (data.success) {
        alert("User created! Please login.");
        if (onSignupSuccess) onSignupSuccess();
      } else {
        alert(data.message || "Signup failed");
      }
    } catch (err) {
      console.error("Signup error:", err);
      alert("Signup failed. Please try again.");
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="max-w-sm mx-auto mt-10 p-4 border rounded shadow"
    >
      <h2 className="text-xl font-bold mb-4">Signup</h2>
      <input
        type="text"
        placeholder="Name"
        value={name}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          setName(e.target.value)
        }
        className="mb-2 p-2 w-full border rounded"
        required
      />
      <input
        type="email"
        placeholder="Email"
        value={email}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          setEmail(e.target.value)
        }
        className="mb-2 p-2 w-full border rounded"
        required
      />
      <input
        type="password"
        placeholder="Password"
        value={password}
        onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
          setPassword(e.target.value)
        }
        className="mb-2 p-2 w-full border rounded"
        required
      />
      <button
        type="submit"
        className="bg-green-500 text-white p-2 rounded w-full hover:bg-green-600"
      >
        Signup
      </button>
    </form>
  );
}
