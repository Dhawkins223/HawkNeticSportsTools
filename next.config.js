/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true
  },
  // Output standalone for Firebase Functions
  output: 'standalone',
  // Disable image optimization for Firebase (or configure for your needs)
  images: {
    unoptimized: true,
  },
};

module.exports = nextConfig;
