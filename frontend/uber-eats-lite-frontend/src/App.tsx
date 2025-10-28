import { BrowserRouter, Routes, Route, Link } from "react-router-dom";
import Home from "./pages/Home";
import Orders from "./pages/Orders";
import Users from "./pages/Users";
import Drivers from "./pages/Drivers";
import Notifications from "./pages/Notifications";
import Payments from "./pages/Payments";

function App() {
  return (
    <BrowserRouter>
      <nav className="flex flex-wrap gap-4 bg-gray-100 p-4 shadow">
        <Link to="/" className="hover:text-green-600 font-medium">Home</Link>
        <Link to="/orders" className="hover:text-green-600 font-medium">Orders</Link>
        <Link to="/users" className="hover:text-green-600 font-medium">Users</Link>
        <Link to="/drivers" className="hover:text-green-600 font-medium">Drivers</Link>
        <Link to="/notifications" className="hover:text-green-600 font-medium">Notifications</Link>
        <Link to="/payments" className="hover:text-green-600 font-medium">Payments</Link>
      </nav>

      <div className="p-6">
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/orders" element={<Orders />} />
          <Route path="/users" element={<Users />} />
          <Route path="/drivers" element={<Drivers />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/payments" element={<Payments />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
