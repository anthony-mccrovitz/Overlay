export const metadata = { title: "Privacy Policy — Overlay" };

export default function PrivacyPage() {
  return (
    <article style={{ maxWidth: 740, color: "var(--text)", lineHeight: 1.7, fontSize: 14 }}>
      <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)" }}>Privacy Policy</h1>
      <p style={{ color: "var(--text-muted)" }}>Last updated: {new Date().toLocaleDateString()}</p>

      <h2 style={h2}>1. What we collect</h2>
      <p>
        We collect only what we need to deliver the service: your email address (for account
        access and product communication) and billing data processed by Stripe. We do not collect
        bank account information, government IDs, or sensitive personal data.
      </p>

      <h2 style={h2}>2. How we use it</h2>
      <p>
        Your email is used to authenticate sign-in (via one-time magic link), grant subscriber
        access, and send transactional emails about your subscription. We do not sell, rent, or
        share your data with third-party marketers.
      </p>

      <h2 style={h2}>3. Service providers we use</h2>
      <ul style={{ paddingLeft: 20 }}>
        <li><strong>Stripe</strong> — payment processing. See Stripe&apos;s privacy policy.</li>
        <li><strong>Resend</strong> — email delivery for sign-in links and product emails.</li>
        <li><strong>Vercel</strong> — hosting and request logs.</li>
      </ul>

      <h2 style={h2}>4. Cookies</h2>
      <p>
        We use a single session cookie to keep you signed in. No third-party advertising or
        tracking cookies are set.
      </p>

      <h2 style={h2}>5. Your rights</h2>
      <p>
        You may request a copy of the data we hold on you, or request deletion of your account and
        associated data, by emailing the address in the footer. We will respond within 30 days.
      </p>

      <h2 style={h2}>6. Children</h2>
      <p>
        Overlay is not directed at children under 18. We do not knowingly collect data from anyone
        under 18.
      </p>

      <h2 style={h2}>7. Contact</h2>
      <p>
        Privacy questions? Email{" "}
        <a href="mailto:anthonymccrovitz02@gmail.com" style={{ color: "var(--indigo)" }}>
          anthonymccrovitz02@gmail.com
        </a>.
      </p>
    </article>
  );
}

const h2 = { fontSize: 16, fontWeight: 700, color: "var(--text-bright)", marginTop: 24, marginBottom: 8 } as const;
