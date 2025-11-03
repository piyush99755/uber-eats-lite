import React from "react";

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: "primary" | "secondary" | "danger";
  loading?: boolean;
}

export const Button: React.FC<ButtonProps> = ({
  variant = "primary",
  loading = false,
  className = "",
  children,
  ...props
}) => {
  const baseStyles =
    "rounded-lg px-4 py-2 font-medium transition focus:outline-none focus:ring disabled:opacity-50";

  const variants = {
    primary: "bg-green-600 hover:bg-green-700 text-white focus:ring-green-300",
    secondary: "bg-gray-200 hover:bg-gray-300 text-gray-700 focus:ring-gray-400",
    danger: "bg-red-600 hover:bg-red-700 text-white focus:ring-red-400",
  };

  return (
    <button
      className={`${baseStyles} ${variants[variant]} ${className}`}
      disabled={loading || props.disabled}
      {...props}
    >
      {loading ? "⏳ Loading..." : children}
    </button>
  );
};
