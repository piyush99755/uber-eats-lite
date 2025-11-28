import { NavLink } from "react-router-dom";
import {
  Users,
  Truck,
  CreditCard,
  Bell,
  ShoppingBag,
  UserCircle,
  ClipboardList,
  Trash2
} from "lucide-react";

interface SidebarProps {
  role: string | null;
  onLogout?: () => void;
}

export default function Sidebar({ role, onLogout }: SidebarProps) {
  // Base user links
  const links: { name: string; path: string; icon: JSX.Element }[] = [];

  if (role === "user") {
    links.push(
      { name: "Orders", path: "/orders", icon: <ShoppingBag size={18} /> },
      { name: "Payments", path: "/payments", icon: <CreditCard size={18} /> }
    );
  }

  if (role === "admin") {
    links.push(
      { name: "Orders", path: "/orders", icon: <ShoppingBag size={18} /> }, // ✅ Admin can see orders
      { name: "Users", path: "/users", icon: <Users size={18} /> },
      { name: "Drivers", path: "/drivers", icon: <Truck size={18} /> },
      { name: "Events", path: "/events", icon: <Bell size={18} /> }
    );
  }

  if (role === "driver") {
    links.push(
      { name: "My Deliveries", path: "/driver/orders", icon: <ClipboardList size={18} /> },
      { name: "My Profile", path: "/driver/profile", icon: <UserCircle size={18} /> }
    );
  }

  return (
    <div className="w-60 h-screen bg-gray-900 text-white flex flex-col p-4 space-y-4">
      <h2 className="text-xl font-bold mb-6">🍔 Uber Eats Lite</h2>

      {links.map((link) => (
        <NavLink
          key={link.path}
          to={link.path}
          className={({ isActive }) =>
            `block p-2 rounded-md flex items-center gap-2 ${
              isActive
                ? "bg-green-600 text-white"
                : "text-gray-300 hover:bg-gray-700 hover:text-white"
            }`
          }
        >
          {link.icon}
          <span>{link.name}</span>
        </NavLink>
      ))}

      {/* DRIVER ONLY — Delete Profile */}
      {role === "driver" && (
        <button
          onClick={() => {
            if (!confirm("Delete your driver profile permanently?")) return;
            // Handle deletion here or in DriverProfile
          }}
          className="mt-2 bg-red-500 hover:bg-red-600 text-white p-2 rounded flex items-center gap-2"
        >
          <Trash2 size={16} />
          Delete Profile
        </button>
      )}

      <button
        onClick={onLogout}
        className="mt-auto bg-red-500 hover:bg-red-600 text-white p-2 rounded"
      >
        Logout
      </button>
    </div>
  );
}
