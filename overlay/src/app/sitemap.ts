import { MetadataRoute } from "next";

const BASE_URL = process.env.NEXT_PUBLIC_SITE_URL || "https://overlay-gray.vercel.app";

export default function sitemap(): MetadataRoute.Sitemap {
  const now = new Date();

  return [
    // Core app pages
    { url: `${BASE_URL}/`, lastModified: now, changeFrequency: "daily", priority: 1.0 },
    { url: `${BASE_URL}/slate`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${BASE_URL}/record`, lastModified: now, changeFrequency: "daily", priority: 0.9 },
    { url: `${BASE_URL}/picks`, lastModified: now, changeFrequency: "daily", priority: 0.8 },
    { url: `${BASE_URL}/models`, lastModified: now, changeFrequency: "weekly", priority: 0.7 },

    // Free tools — highest SEO priority (keyword targets)
    { url: `${BASE_URL}/tools`, lastModified: now, changeFrequency: "weekly", priority: 0.9 },
    { url: `${BASE_URL}/no-vig`, lastModified: now, changeFrequency: "monthly", priority: 0.95 },
    { url: `${BASE_URL}/clv-calculator`, lastModified: now, changeFrequency: "monthly", priority: 0.95 },

    // Legal / static
    { url: `${BASE_URL}/privacy`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
    { url: `${BASE_URL}/terms`, lastModified: now, changeFrequency: "yearly", priority: 0.2 },
  ];
}
