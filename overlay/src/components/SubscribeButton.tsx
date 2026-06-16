export function SubscribeButton({ children = "Subscribe — $19/mo" }: { children?: React.ReactNode }) {
  const href = process.env.NEXT_PUBLIC_STRIPE_PAYMENT_LINK || "#";
  return (
    <a href={href} className="btn-primary" target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  );
}
