// Client-side topic guess for the typed question (a hint only; never sent to scoring).
// "validated" = the rubric was fitted and tested on this topic (rounds 1-4);
// the other four are SlopWatch's round-5 out-of-domain check.

export interface Topic { id: string; label: string; validated: boolean }

const TOPICS: (Topic & { words: string[] })[] = [
  { id: "scams_safety", label: "Scams and safety", validated: false,
    words: ["scam", "fraud", "fake", "otp", "kyc", "cyber", "phishing", "hacked", "spam", "telegram", "task job", "money back", "safe or fake", "real or fake", "loan app", "rbi registered"] },
  { id: "government_services", label: "Government services", validated: false,
    words: ["ration", "passport", "pm kisan", "kisan", "licence", "license", "scholarship", "voter", "ayushman", "certificate", "pan card", "aadhaar", "aadhar", "epfo", "uan", "government", "scheme", "portal"] },
  { id: "legal_rights", label: "Legal rights", validated: false,
    words: ["fir", "police", "legal", "lawyer", "rti", "rights", "consumer complaint", "court", "notice", "landlord", "tenant", "property", "divorce", "bail", "unpaid salary"] },
  { id: "education_exams", label: "Education and exams", validated: false,
    words: ["neet", "jee", "cuet", "upsc", "gate", "cat exam", "exam", "cutoff", "admission", "college", "syllabus", "course", "study abroad", "university", "percentile", "rank", "board result", "study"] },
  { id: "health", label: "Health", validated: true,
    words: ["medicine", "tablet", "symptom", "diet", "pain", "fever", "diabetes", "sugar", "bp", "blood", "cholesterol", "pregnan", "vitamin", "remed", "treatment", "dolo", "paracetamol", "cough", "thyroid", "liver", "pcos", "haemoglobin", "doctor", "side effect", "dengue", "acidity", "uric", "bp range", "blood pressure", "weight loss"] },
  { id: "personal_finance", label: "Money", validated: true,
    words: ["sip", "tax", "itr", "loan", "credit card", "insurance", "fixed deposit", " fd", "invest", "mutual fund", "cibil", "ppf", "nps", "elss", "emergency fund", "debt", "stock", "interest rate", "savings"] },
  { id: "product_reviews", label: "Products", validated: true,
    words: ["~best ", "~under ", "buy", "review", "price", "budget", "smartphone", "laptop", "earbuds", "purifier", "ac ", "fridge", "refrigerator", "geyser", "trimmer", "mattress", "shoes", "fryer", "vacuum", "fan ", "mixer", "grinder", "washing machine", "power bank", "smartwatch", "phone under"] },
  { id: "tech_howto", label: "Tech how-to", validated: true,
    words: ["~how to", "android", "iphone", "whatsapp", "gmail", "windows", "~app", "upi", "download", "~link ", "recover", "transfer", "~block", "speed up", "settings", "fastag", "wifi", "internet", "pnr", "ceir", "lost phone", "~fix"] },
];

export function guessTopic(q: string): Topic | null {
  const s = ` ${q.toLowerCase()} `;
  if (s.trim().length < 3) return null;
  let best: (typeof TOPICS)[number] | null = null;
  let bestScore = 0;
  for (const t of TOPICS) {
    // longer, more specific phrases count more; earlier topics win ties (most specific first)
    // generic phrases ("~how to", "~best ") count 1; specific words count by length (max 8)
    const score = t.words.reduce((n, w) => {
      const generic = w.startsWith("~"), word = generic ? w.slice(1) : w;
      return s.includes(word) ? n + (generic ? 1 : Math.min(word.trim().length, 8)) : n;
    }, 0);
    if (score > bestScore) { best = t; bestScore = score; }
  }
  return best && bestScore >= 3 ? { id: best.id, label: best.label, validated: best.validated } : null;
}
