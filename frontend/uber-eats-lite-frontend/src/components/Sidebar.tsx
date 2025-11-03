import { NavLink } from "react-router-dom";
import { LayoutDashboard, Users, Truck, CreditCard, Bell, Home, ShoppingBag } from "lucide-react";

interface SidebarProps {
  onNavigate?: () => void;   // function prop for closing sidebar on mobile
  activePath?: string;       // highlight active link
}

export default function Sidebar({ onNavigate, activePath }: SidebarProps) {
  const links = [
    { name: "Dashboard", path: "/" },
    { name: "Users", path: "/users" },
    { name: "Orders", path: "/orders" },
    { name: "Drivers", path: "/drivers" },
    { name: "Payments", path: "/payments" },
    { name: "Events", path: "/events" },
  ];

  return (
    <div className="w-60 h-screen bg-gray-900 text-white flex flex-col p-4 space-y-4">
      <h2 className="text-xl font-bold mb-6">🍔 Uber Eats Lite</h2>
      {links.map((link) => (
        <NavLink
          key={link.path}
          to={link.path}
          onClick={onNavigate} // ✅ now properly typed
          className={({ isActive }) =>
            `block p-2 rounded-md flex items-center gap-2 ${
              isActive
                ? "bg-green-600 text-white"
                : "text-gray-300 hover:bg-gray-700 hover:text-white"
            }`
          }
        >
          {/* Optionally add icons */}
          {link.name === "Dashboard" && <LayoutDashboard size={18} />}
          {link.name === "Users" && <Users size={18} />}
          {link.name === "Orders" && <ShoppingBag size={18} />}
          {link.name === "Drivers" && <Truck size={18} />}
          {link.name === "Payments" && <CreditCard size={18} />}
          {link.name === "Events" && <Bell size={18} />}
          <span>{link.name}</span>
        </NavLink>
      ))}
    </div>
  );
}
