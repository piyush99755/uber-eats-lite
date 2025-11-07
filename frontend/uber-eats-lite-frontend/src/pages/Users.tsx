import { useEffect, useState } from "react";
import api from "../api/api";
import { Button } from "../components/Button";
import { Modal } from "../components/Modal";
import { toast, ToastContainer } from "react-toastify";
import "react-toastify/dist/ReactToastify.css";

interface User {
  id: string;
  name: string;
  email: string;
}

interface APIResponse<T> {
  success: boolean;
  data: T;
  message?: string;
}

export default function Users() {
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [loading, setLoading] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [form, setForm] = useState({ name: "", email: "" });

  const API_BASE = "/users";

  const fetchUsers = async () => {
    try {
      const res = await api.get<APIResponse<User[]>>(`${API_BASE}/users`);
      if (res.data.success && res.data.data) {
        setUsers([...res.data.data].reverse());
        setError("");
      } else {
        setUsers([]);
        setError(res.data.message || "Failed to fetch users");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    fetchUsers();
  }, []);

  const validateForm = () => {
    if (!form.name.trim()) {
      toast.error("Name cannot be empty");
      return false;
    }
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    if (!emailRegex.test(form.email)) {
      toast.error("Invalid email address");
      return false;
    }
    return true;
  };

  const handleSubmit = async () => {
    if (!validateForm()) return;
    setLoading(true);

    try {
      if (editingUser) {
        // Update existing user
        const res = await api.put<APIResponse<User>>(
          `${API_BASE}/users/${editingUser.id}`,
          form
        );
        if (res.data.success && res.data.data) {
          setUsers((prev) =>
            prev.map((u) => (u.id === editingUser.id ? res.data.data : u))
          );
          toast.success("User updated successfully");
        } else {
          toast.error(res.data.message || "Failed to update user");
        }
      } else {
        // Create new user
        const res = await api.post<APIResponse<User>>(`${API_BASE}/users`, form);
        if (res.data.success && res.data.data) {
          setUsers((prev) => [res.data.data, ...prev]);
          toast.success("User created successfully");
        } else {
          toast.error(res.data.message || "Failed to create user");
        }
      }

      setShowModal(false);
      setForm({ name: "", email: "" });
      setEditingUser(null);
    } catch (err: unknown) {
      // Type-safe error handling
      const message = err instanceof Error ? err.message : String(err);
      console.error(message);
      toast.error("Server error"); // show toast notification
    }
 finally {
      setLoading(false);
    }
  };

  const handleDeleteUser = async (id: string) => {
    if (!confirm("Delete this user?")) return;
    try {
      const res = await api.delete<APIResponse<null>>(`${API_BASE}/users/${id}`);
      if (res.data.success) {
        setUsers((prev) => prev.filter((u) => u.id !== id));
        toast.success("User deleted successfully");
      } else toast.error(res.data.message || "Failed to delete user");
    } catch {
      toast.error("Failed to delete user");
    }
  };

  const openEditModal = (user: User) => {
    setEditingUser(user);
    setForm({ name: user.name, email: user.email });
    setShowModal(true);
  };

  return (
    <div className="p-6">
      <ToastContainer position="top-right" />
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-3xl font-bold">👥 Users</h1>
        <Button
          onClick={() => {
            setEditingUser(null);
            setForm({ name: "", email: "" });
            setShowModal(true);
          }}
        >
          ➕ Add User
        </Button>
      </div>

      {error && <p className="text-red-500 mb-4">Error: {error}</p>}

      <div className="grid gap-3">
        {users.length ? (
          users.map((user) => (
            <div
              key={user.id}
              className="border rounded-lg p-4 bg-white shadow flex justify-between items-center"
            >
              <div>
                <p className="font-semibold">{user.name}</p>
                <p className="text-gray-500 text-sm">{user.email}</p>
              </div>
              <div className="flex gap-2">
                <Button onClick={() => openEditModal(user)} className="bg-blue-500 hover:bg-blue-600 text-white px-3 py-1 rounded">
                  ✏️ Edit
                </Button>
                <Button onClick={() => handleDeleteUser(user.id)} className="bg-red-500 hover:bg-red-600 text-white px-3 py-1 rounded">
                  🗑 Delete
                </Button>
              </div>
            </div>
          ))
        ) : (
          <p>No users found</p>
        )}
      </div>

      <Modal show={showModal} onClose={() => setShowModal(false)} title={editingUser ? "Edit User" : "Add New User"}>
        <input
          type="text"
          placeholder="Full Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          className="border p-2 w-full mb-3 rounded"
        />
        <input
          type="email"
          placeholder="Email"
          value={form.email}
          onChange={(e) => setForm({ ...form, email: e.target.value })}
          className="border p-2 w-full mb-4 rounded"
        />
        <Button onClick={handleSubmit} loading={loading} className="w-full">
          {editingUser ? "Update User" : "Create User"}
        </Button>
      </Modal>
    </div>
  );
}
