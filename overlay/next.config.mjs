/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,

  // Prevent Next.js file tracing from bundling the local picks output directory
  // into serverless functions. The API reads from pre-built slate_data.json instead.
  // Without this, output/picks/ (260MB+) gets included and busts the 250MB limit.
  experimental: {
    outputFileTracingExcludes: {
      "/api/slate": [
        "../../output/**",
        "../output/**",
        "../../data/**",
        "../../logs/**",
      ],
    },
  },
};

export default nextConfig;
