import { NavLink } from "react-router-dom";

export default function Sidebar() {
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
      {links.map(link => (
        <NavLink
          key={link.path}
          to={link.path}
          className={({ isActive }) =>
            `block p-2 rounded-md ${isActive ? "bg-green-600" : "hover:bg-gray-700"}`
          }
        >
          {link.name}
        </NavLink>
      ))}
    </div>
  );
}
