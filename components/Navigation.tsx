"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

export function Navigation() {
  const [isOpen, setIsOpen] = useState(false);
  const pathname = usePathname();
  const menuRef = useRef<HTMLDivElement>(null);

  const navLinks = [
    { href: "/games", label: "Games" },
    { href: "/props", label: "Props" },
    { href: "/tickets", label: "Tickets" },
    { href: "/about-model", label: "Transparency" },
    { href: "/chat", label: "AI Chat" },
    { href: "/data", label: "Data" },
    { href: "/historical", label: "Historical" },
    { href: "/settings", label: "Settings" },
  ];

  const toggleMenu = () => {
    setIsOpen(!isOpen);
  };

  const closeMenu = () => {
    setIsOpen(false);
  };

  // Close menu when clicking outside
  useEffect(() => {
    if (!isOpen) return;

    const handleClickOutside = (event: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        closeMenu();
      }
    };

    document.addEventListener("mousedown", handleClickOutside);
    // Prevent body scroll when menu is open on mobile
    document.body.style.overflow = "hidden";

    return () => {
      document.removeEventListener("mousedown", handleClickOutside);
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  // Close menu when route changes
  useEffect(() => {
    closeMenu();
  }, [pathname]);

  return (
    <nav className="relative z-[100]" ref={menuRef}>
      {/* Hamburger Button */}
      <button
        onClick={toggleMenu}
        className="flex flex-col justify-center items-center gap-1.5 w-12 h-12 rounded-lg bg-surface2 border border-border hover:bg-surface hover:border-borderHover transition-all duration-200"
        aria-label="Toggle menu"
        aria-expanded={isOpen}
      >
        <span
          className={`block h-[2px] w-6 bg-white transition-all duration-300 origin-center ${
            isOpen ? "rotate-45 translate-y-[7px]" : ""
          }`}
        />
        <span
          className={`block h-[2px] w-6 bg-white transition-all duration-300 ${
            isOpen ? "opacity-0" : ""
          }`}
        />
        <span
          className={`block h-[2px] w-6 bg-white transition-all duration-300 origin-center ${
            isOpen ? "-rotate-45 -translate-y-[7px]" : ""
          }`}
        />
      </button>

      {/* Menu Dropdown */}
      <div
        className={`absolute right-0 top-full mt-2 w-72 card p-2 z-[9999] shadow-2xl transition-all duration-300 ease-out ${
          isOpen
            ? "opacity-100 visible translate-y-0 scale-100"
            : "opacity-0 invisible -translate-y-2 scale-95 pointer-events-none"
        }`}
      >
        <div className="flex flex-col gap-1.5">
          {navLinks.map((link) => {
            const isActive = pathname === link.href;
            return (
              <Link
                key={link.href}
                href={link.href}
                onClick={closeMenu}
                className={`px-4 py-3 rounded-lg font-semibold text-sm transition-all duration-200 ${
                  isActive
                    ? "bg-accent text-white border border-accent shadow-lg"
                    : "bg-surface2 hover:bg-surface border border-border hover:border-borderHover text-text hover:text-white"
                }`}
              >
                {link.label}
              </Link>
            );
          })}
        </div>
      </div>

      {/* Overlay (for mobile) */}
      {isOpen && (
        <div
          className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[9998] md:hidden"
          onClick={closeMenu}
        />
      )}
    </nav>
  );
}

