import { useState, useEffect } from "react";

interface SignupProps {
  onSignupSuccess?: () => void;
}

export default function Signup({ onSignupSuccess }: SignupProps) {
  const [role, setRole] = useState<"user" | "driver">("user");

  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Driver-specific fields
  const [vehicle, setVehicle] = useState("");
  const [licenseNumber, setLicenseNumber] = useState("");

  // Errors
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [backendError, setBackendError] = useState<Record<string, string>>({});

  // Live validation
  useEffect(() => {
    const newErrors: Record<string, string> = {};

    if (!name.trim()) newErrors.name = "Name is required";

    if (!email.trim()) newErrors.email = "Email is required";
    else if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) newErrors.email = "Invalid email format";

    if (!password.trim()) newErrors.password = "Password is required";
    else if (password.length < 6) newErrors.password = "Password must be at least 6 characters";

    if (role === "driver") {
      if (!vehicle.trim()) newErrors.vehicle = "Vehicle is required for drivers";
      if (!licenseNumber.trim()) newErrors.licenseNumber = "License number is required for drivers";
    }

    setErrors(newErrors);
    setBackendError({}); // clear backend errors on input change
  }, [name, email, password, vehicle, licenseNumber, role]);

  const canSubmit = Object.keys(errors).length === 0;

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!canSubmit) return;

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
        // Map backend errors to relevant fields if possible
        const fieldErrors: Record<string, string> = {};
        if (data.message?.toLowerCase().includes("email")) fieldErrors.email = data.message;
        else fieldErrors.general = data.message || data.error || "Signup failed";

        setBackendError(fieldErrors);
      }
    } catch (err) {
      console.error("Signup error:", err);
      setBackendError({ general: "Signup failed. Please try again." });
    }
  };

  return (
    <form
      onSubmit={handleSubmit}
      className="max-w-sm mx-auto mt-10 p-6 border rounded shadow bg-white"
    >
      <h2 className="text-2xl font-bold mb-4">Sign Up</h2>

      {/* Role toggle */}
      <div className="flex gap-2 mb-4">
        <button
          type="button"
          onClick={() => setRole("user")}
          className={`p-2 flex-1 rounded ${role === "user" ? "bg-green-600 text-white" : "bg-gray-200"}`}
        >
          User
        </button>
        <button
          type="button"
          onClick={() => setRole("driver")}
          className={`p-2 flex-1 rounded ${role === "driver" ? "bg-green-600 text-white" : "bg-gray-200"}`}
        >
          Driver
        </button>
      </div>

      {backendError.general && <p className="text-red-500 mb-2">{backendError.general}</p>}

      {/* Name */}
      <div className="mb-2">
        <input
          type="text"
          placeholder="Full Name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          className={`p-2 w-full border rounded ${errors.name || backendError.name ? "border-red-500" : "border-gray-300"}`}
        />
        {(errors.name || backendError.name) && <p className="text-red-500 text-sm mt-1">{errors.name || backendError.name}</p>}
      </div>

      {/* Email */}
      <div className="mb-2">
        <input
          type="email"
          placeholder="Email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={`p-2 w-full border rounded ${errors.email || backendError.email ? "border-red-500" : "border-gray-300"}`}
        />
        {(errors.email || backendError.email) && <p className="text-red-500 text-sm mt-1">{errors.email || backendError.email}</p>}
      </div>

      {/* Password */}
      <div className="mb-2">
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={`p-2 w-full border rounded ${errors.password || backendError.password ? "border-red-500" : "border-gray-300"}`}
        />
        {(errors.password || backendError.password) && <p className="text-red-500 text-sm mt-1">{errors.password || backendError.password}</p>}
      </div>

      {/* Driver fields */}
      {role === "driver" && (
        <>
          <div className="mb-2">
            <input
              type="text"
              placeholder="Vehicle (e.g., Toyota Prius)"
              value={vehicle}
              onChange={(e) => setVehicle(e.target.value)}
              className={`p-2 w-full border rounded ${errors.vehicle || backendError.vehicle ? "border-red-500" : "border-gray-300"}`}
            />
            {(errors.vehicle || backendError.vehicle) && <p className="text-red-500 text-sm mt-1">{errors.vehicle || backendError.vehicle}</p>}
          </div>

          <div className="mb-2">
            <input
              type="text"
              placeholder="License Number"
              value={licenseNumber}
              onChange={(e) => setLicenseNumber(e.target.value)}
              className={`p-2 w-full border rounded ${errors.licenseNumber || backendError.licenseNumber ? "border-red-500" : "border-gray-300"}`}
            />
            {(errors.licenseNumber || backendError.licenseNumber) && <p className="text-red-500 text-sm mt-1">{errors.licenseNumber || backendError.licenseNumber}</p>}
          </div>
        </>
      )}

      {/* Submit */}
      <button
        type="submit"
        disabled={!canSubmit}
        className={`w-full p-2 rounded mt-3 ${
          canSubmit ? "bg-green-500 hover:bg-green-600 text-white" : "bg-gray-300 text-gray-600 cursor-not-allowed"
        }`}
      >
        Sign Up
      </button>
    </form>
  );
}
