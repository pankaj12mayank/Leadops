export interface SiteContent {
  seo: {
    title: string;
    metaDescription: string;
    keywords: string;
  };
  brand: {
    name: string;
    tagline: string;
  };
  hero: {
    title: string;
    subtitle: string;
    cta: string;
  };
  features: {
    heading: string;
    items: Array<{ title: string; description: string }>;
  };
  search: {
    heading: string;
    subtitle: string;
    labels: { source: string; keyword: string; location: string; maxPages: string };
    placeholders: { keyword: string; location: string };
    button: string;
  };
  results: {
    empty: string;
    locked: string;
    unlockCta: string;
    downloadCta: string;
  };
  pricing: {
    heading: string;
    subtitle: string;
    perExport: string;
    price: string;
    priceDescription: string;
    features: string[];
    cta: string;
  };
  faq: {
    heading: string;
    items: Array<{ question: string; answer: string }>;
  };
  nav: {
    links: Array<{ label: string; href: string }>;
  };
}
