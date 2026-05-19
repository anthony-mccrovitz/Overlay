export const metadata = { title: "Terms of Service — Overlay" };

export default function TermsPage() {
  return (
    <article style={{ maxWidth: 740, color: "var(--text)", lineHeight: 1.7, fontSize: 14 }}>
      <h1 style={{ fontSize: 28, fontWeight: 800, color: "var(--text-bright)" }}>Terms of Service</h1>
      <p style={{ color: "var(--text-muted)" }}>Last updated: {new Date().toLocaleDateString()}</p>

      <h2 style={h2}>1. What Overlay is</h2>
      <p>
        Overlay (&quot;Overlay,&quot; &quot;we,&quot; &quot;us&quot;) is a sports-analytics
        subscription service that provides users with the output of a proprietary statistical model
        applied to publicly available sports data. Outputs may include projections, probability
        estimates, written analysis, and quantitative summaries. Overlay is an informational and
        educational product. <strong>Overlay is not a sportsbook, broker, advisor, or financial
        institution.</strong> Overlay does not accept, place, hold, or facilitate any wager,
        deposit, or financial transaction on behalf of users.
      </p>

      <h2 style={h2}>2. Eligibility</h2>
      <p>
        You must be at least 18 years old (21+ in jurisdictions where applicable) and legally
        permitted to access sports content in your location to use Overlay. You are solely
        responsible for ensuring your use complies with all laws of your jurisdiction.
      </p>

      <h2 style={h2}>3. Subscription &amp; billing</h2>
      <p>
        Overlay is offered as a recurring monthly subscription billed through Stripe. By
        subscribing, you authorize us to charge your payment method on a recurring basis until you
        cancel. You may cancel at any time by emailing the support address in the footer; access
        continues through the end of the paid period. Refunds are issued at our sole discretion.
      </p>

      <h2 style={h2}>4. No guarantees</h2>
      <p>
        Sports outcomes are inherently uncertain. Past performance of any model, pick, or analysis
        provided through Overlay is not indicative of future results. We make no warranty, express
        or implied, that any pick will win, that any model will remain profitable, or that any
        information provided will be free of errors. <strong>You assume all risk for any decisions
        you make based on Overlay content.</strong>
      </p>

      <h2 style={h2}>5. Acceptable use</h2>
      <p>
        You may not redistribute, resell, scrape, or commercially reuse Overlay content. Your
        subscription is for personal use only. Sharing access credentials may result in
        cancellation without refund.
      </p>

      <h2 style={h2}>6. Limitation of liability</h2>
      <p>
        To the maximum extent permitted by law, Overlay&apos;s total liability for any claim arising
        out of or relating to the service is limited to the amount you paid us in the three months
        preceding the claim. We are not liable for any indirect, consequential, or incidental
        damages, including lost profits.
      </p>

      <h2 style={h2}>7. Changes</h2>
      <p>
        We may update these terms from time to time. Material changes will be communicated by email
        to active subscribers.
      </p>

      <h2 style={h2}>8. Contact</h2>
      <p>
        Questions about these terms? Email{" "}
        <a href="mailto:anthonymccrovitz02@gmail.com" style={{ color: "var(--indigo)" }}>
          anthonymccrovitz02@gmail.com
        </a>.
      </p>
    </article>
  );
}

const h2 = { fontSize: 16, fontWeight: 700, color: "var(--text-bright)", marginTop: 24, marginBottom: 8 } as const;
