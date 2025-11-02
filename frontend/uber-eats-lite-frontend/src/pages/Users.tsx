import { useEffect, useState } from "react";
import api from "../api/api";


console.log("Base URL:", import.meta.env.VITE_API_BASE_URL);

// Define a User type
interface User {
  id: number;
  name: string;
  email?: string;
  phone?: string;
}

export default function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState<string>("");

  useEffect(() => {
  api.get<User[]>("/users/users")
    .then(res => {
      console.log("Fetched users:", res.data);
      setUsers(res.data);
    })
    .catch(err => {
      console.error("Error fetching users:", err);
      setError(err.message);
    });
}, []);


  

  return (
    
    
    <div className="text-center mt-10">
      <h1 className="text-3xl font-bold">👥 Users Page</h1>
      <p className="text-gray-600 mt-2">
        Manage customers, their profiles, and order histories here.
      </p>

      {error && <p className="text-red-500 mt-4">Error: {error}</p>}

      <div className="mt-6 space-y-2">
        {users.length > 0 ? (
          users.map((user) => (
            <div key={user.id} className="border rounded-lg p-3 mx-auto w-1/2">
              <p>{user.name}</p>
              <p className="text-gray-500 text-sm">{user.email}</p>
            </div>
          ))
        ) : (
          <p className="text-gray-500">No users found or loading...</p>
        )}
      </div>
    </div>
  );
}
