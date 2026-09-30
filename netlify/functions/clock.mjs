// השעון האמין של המכונה: Netlify מריץ את זה כל 10 דקות, וזה מפעיל את ה-workflows ב-GitHub בשעה הנכונה בישראל.
// GitHub Actions cron מאחר שעות; Netlify Scheduled Functions מדייקים לדקה.
// דורש משתנה סביבה GH_DISPATCH_TOKEN (fine-grained PAT של eyal-hg על הריפו hk-social, הרשאת Actions: Read and write).
const REPO = "eyal-hg/hk-social";
const SLOTS = [                       // [שעה:דקה בישראל, workflow, inputs]
  ["07:00", "ads-report.yml", {}],     // הדוח לפני המייל של 08:00
  ["10:00", "publish.yml", { dry_run: false }],   // הפוסטים של היום
];

function israelNow() {
  const p = Object.fromEntries(new Intl.DateTimeFormat("en-GB", { timeZone: "Asia/Jerusalem", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
    .formatToParts(new Date()).filter(x => x.type === "hour" || x.type === "minute").map(x => [x.type, +x.value]));
  return p.hour * 60 + p.minute;
}

export default async () => {
  const token = process.env.GH_DISPATCH_TOKEN;
  if (!token) return new Response("GH_DISPATCH_TOKEN missing", { status: 500 });
  const now = israelNow(), fired = [];
  for (const [hm, wf, inputs] of SLOTS) {
    const [h, m] = hm.split(":").map(Number), t = h * 60 + m;
    if (now < t || now >= t + 10) continue;          // the run every 10 minutes lands in this window exactly once
    const r = await fetch(`https://api.github.com/repos/${REPO}/actions/workflows/${wf}/dispatches`, {
      method: "POST", headers: { Authorization: `Bearer ${token}`, Accept: "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28" },
      body: JSON.stringify({ ref: "main", inputs }),
    });
    fired.push(`${wf}:${r.status}`);
  }
  console.log("israel", now, "fired", fired.join(",") || "nothing");
  return new Response(fired.join(",") || "nothing due");
};

export const config = { schedule: "*/10 * * * *" };
