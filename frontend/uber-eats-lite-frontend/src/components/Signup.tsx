import { useState } from "react";

interface SignupProps {
  onSignupSuccess?: () => void;
}

export default function Signup({ onSignupSuccess }: SignupProps) {
  const [role, setRole] = useState<"user" | "driver">("user");

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // driver-only
  const [vehicle, setVehicle] = useState("");
  const [licenseNumber, setLicenseNumber] = useState("");

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();

    const body =
      role === "driver"
        ? { name, email, password, role, vehicle, license_number: licenseNumber }
        : { name, email, password, role };

    try {
        const res = await fetch("http://localhost:8000/auth/signup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });

      const data = await res.json();

      if (res.ok) {
        alert("Account created! Please login.");
        if (onSignupSuccess) onSignupSuccess();
      } else {
        alert(data.message || data.error || "Signup failed");
      }
    } catch (err) {
      console.error("Signup error:", err);
      alert("Signup failed. Please try again.");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="max-w-sm mx-auto mt-10 p-4 border rounded shadow bg-white">
      <h2 className="text-xl font-bold mb-4">Signup</h2>

      <div className="flex gap-2 mb-4">
        <button type="button" onClick={() => setRole("user")} className={`p-2 flex-1 rounded ${role === "user" ? "bg-green-600 text-white" : "bg-gray-200"}`}>
          Sign up as User
        </button>
        <button type="button" onClick={() => setRole("driver")} className={`p-2 flex-1 rounded ${role === "driver" ? "bg-green-600 text-white" : "bg-gray-200"}`}>
          Sign up as Driver
        </button>
      </div>

      <input type="text" placeholder="Full Name" value={name} onChange={(e) => setName(e.target.value)} className="mb-2 p-2 w-full border rounded" required />
      <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} className="mb-2 p-2 w-full border rounded" required />
      <input type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} className="mb-2 p-2 w-full border rounded" required />

      {role === "driver" && (
        <>
          <input type="text" placeholder="Vehicle (e.g., Toyota Prius)" value={vehicle} onChange={(e) => setVehicle(e.target.value)} className="mb-2 p-2 w-full border rounded" required />
          <input type="text" placeholder="License Number" value={licenseNumber} onChange={(e) => setLicenseNumber(e.target.value)} className="mb-2 p-2 w-full border rounded" required />
        </>
      )}

      <button type="submit" className="bg-green-500 text-white p-2 rounded w-full hover:bg-green-600 mt-3">Signup</button>
    </form>
  );
}
