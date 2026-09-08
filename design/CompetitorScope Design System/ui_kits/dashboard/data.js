// Fake data shaped exactly like the API contract's response objects.
window.CS_DATA = {
  companies: [
    { id: 'me', name: 'Marketing Eye', website_url: 'marketingeye.com.au' },
    { id: 'taf', name: 'The Athletes Foot', website_url: 'theathletesfoot.com.au' },
  ],
  competitors: {
    me: { id: 'c1', company_id: 'me', name: 'Lyfe Marketing', website_url: 'lyfemarketing.com' },
    taf: { id: 'c2', company_id: 'taf', name: 'JD Sports AU', website_url: 'jd-sports.com.au' },
  },
  targets: {
    me: [
      { id: 't1', url: 'https://lyfemarketing.com/blog', page_type: 'BLOG', classification_method: 'RULE', discovery_status: 'ACTIVE', interval: '6 h' },
      { id: 't2', url: 'https://lyfemarketing.com/pricing', page_type: 'PRICING', classification_method: 'RULE', discovery_status: 'ACTIVE', interval: '12 h' },
      { id: 't3', url: 'https://lyfemarketing.com/services', page_type: 'SERVICES', classification_method: 'LLM', discovery_status: 'ACTIVE', interval: '24 h' },
      { id: 't4', url: 'https://lyfemarketing.com/case-studies', page_type: 'WORK', classification_method: 'LLM', discovery_status: 'SUGGESTED' },
      { id: 't5', url: 'https://lyfemarketing.com/about', page_type: 'ABOUT', classification_method: 'RULE', discovery_status: 'SUGGESTED' },
      { id: 't6', url: 'https://lyfemarketing.com/contact', page_type: 'CONTACT', classification_method: 'RULE', discovery_status: 'DISCARDED' },
      { id: 't7', url: 'https://lyfemarketing.com/privacy-policy', page_type: 'OTHER', classification_method: 'RULE', discovery_status: 'DISCARDED' },
    ],
    taf: [
      { id: 't8', url: 'https://jd-sports.com.au/mens-shoes', page_type: 'PRODUCT_LISTING', classification_method: 'LLM', discovery_status: 'ACTIVE', interval: '6 h' },
      { id: 't9', url: 'https://jd-sports.com.au/blog', page_type: 'BLOG', classification_method: 'RULE', discovery_status: 'ACTIVE', interval: '6 h' },
      { id: 't10', url: 'https://jd-sports.com.au/sale', page_type: 'PRODUCT_LISTING', classification_method: 'LLM', discovery_status: 'SUGGESTED' },
      { id: 't11', url: 'https://jd-sports.com.au/careers', page_type: 'CAREERS', classification_method: 'RULE', discovery_status: 'DISCARDED' },
    ],
  },
  changes: {
    me: [
      { id: 'x1', change_type: 'NEW_BLOG', summary: 'New post: “7 B2B Content Trends Agencies Will Sell in 2026”', target: 'lyfemarketing.com/blog', detected_at: '2 hours ago', is_simulated: false },
      { id: 'x2', change_type: 'PAGE_UPDATE', summary: 'Services page copy changed in 3 sections', target: 'lyfemarketing.com/services', detected_at: '9 hours ago', is_simulated: false },
      { id: 'x3', change_type: 'PRICE_CHANGE', summary: 'Social Media Management retainer price changed', from: '$1,500/mo', to: '$1,750/mo', target: 'lyfemarketing.com/pricing', detected_at: 'Yesterday', is_simulated: false },
      { id: 'x4', change_type: 'NEW_BLOG', summary: 'New post: “How Much Should You Spend on PPC?”', target: 'lyfemarketing.com/blog', detected_at: '3 days ago', is_simulated: false },
    ],
    taf: [
      { id: 'x5', change_type: 'NEW_PRODUCT', summary: 'Added: Nike Air Max Dn8 (Men\'s)', target: 'jd-sports.com.au/mens-shoes', detected_at: '40 minutes ago', is_simulated: false },
      { id: 'x6', change_type: 'PRICE_CHANGE', summary: 'Nike Pegasus 41 price changed', from: '$219.99', to: '$179.99', target: 'jd-sports.com.au/mens-shoes', detected_at: '5 hours ago', is_simulated: false },
      { id: 'x7', change_type: 'PRODUCT_REMOVED', summary: 'Removed: adidas Samba OG (Core Black)', target: 'jd-sports.com.au/mens-shoes', detected_at: 'Yesterday', is_simulated: false },
      { id: 'x8', change_type: 'NEW_BLOG', summary: 'New post: “Best Running Shoes for Winter Training”', target: 'jd-sports.com.au/blog', detected_at: '2 days ago', is_simulated: false },
    ],
  },
  runs: {
    me: [
      { id: 'r1', target: 'lyfemarketing.com/blog', status: 'SUCCESS', at: '18 min ago' },
      { id: 'r2', target: 'lyfemarketing.com/pricing', status: 'SUCCESS', at: '52 min ago' },
      { id: 'r3', target: 'lyfemarketing.com/services', status: 'FAILED', at: '1 hour ago' },
    ],
    taf: [
      { id: 'r4', target: 'jd-sports.com.au/mens-shoes', status: 'RUNNING', at: 'now' },
      { id: 'r5', target: 'jd-sports.com.au/blog', status: 'SUCCESS', at: '35 min ago' },
    ],
  },
  // What POST /monitoring-targets/<id>/simulate returns, per page type.
  simulations: {
    BLOG: [{ change_type: 'NEW_BLOG', summary: 'New post: “The Agency Retainer Is Dead. Here’s What Replaced It.”' }],
    PRICING: [{ change_type: 'PRICE_CHANGE', summary: 'SEO starter package price changed', from: '$800/mo', to: '$950/mo' }],
    SERVICES: [{ change_type: 'PAGE_UPDATE', summary: 'Services page added a new “AI Content Ops” offering' }],
    PRODUCT_LISTING: [
      { change_type: 'NEW_PRODUCT', summary: 'Added: ASICS Gel-Kayano 32 (Men’s)' },
      { change_type: 'PRICE_CHANGE', summary: 'New Balance 9060 price changed', from: '$239.99', to: '$199.99' },
      { change_type: 'PRODUCT_REMOVED', summary: 'Removed: Puma Speedcat OG' },
    ],
  },
};
