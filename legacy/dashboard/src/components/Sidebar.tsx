'use client'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { BarChart2, TrendingUp, Target, Calculator, FlaskConical } from 'lucide-react'

const NAV = [
  { href: '/picks', label: 'Picks', icon: BarChart2 },
  { href: '/performance', label: 'Performance', icon: TrendingUp },
  { href: '/clv', label: 'CLV', icon: Target },
  { href: '/models', label: 'Models', icon: FlaskConical },
  { href: '/tools', label: 'Tools', icon: Calculator },
]

export default function Sidebar() {
  const path = usePathname()
  return (
    <>
      {/* Desktop left rail — inline display removed so Tailwind md:flex wins */}
      <nav style={{
        width: 200, minHeight: '100vh', background: 'var(--bg-panel)',
        borderRight: '1px solid var(--border)', padding: '24px 12px',
        flexDirection: 'column', gap: 4,
        position: 'sticky', top: 0, alignSelf: 'flex-start', height: '100vh'
      }} className="hidden md:flex">
        <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-muted)', letterSpacing: '0.08em', padding: '0 8px 16px' }}>
          EDGEFINDER
        </div>
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = path.startsWith(href)
          return (
            <Link key={href} href={href} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '9px 12px',
              borderRadius: 8, fontSize: 13, fontWeight: 500, textDecoration: 'none',
              color: active ? 'var(--text-bright)' : 'var(--text-secondary)',
              background: active ? 'var(--indigo-dim)' : 'transparent',
              border: active ? '1px solid rgba(99,102,241,0.25)' : '1px solid transparent',
              transition: 'all 0.15s ease',
            }}>
              <Icon size={15} style={{ color: active ? 'var(--indigo)' : 'var(--text-muted)' }} />
              {label}
            </Link>
          )
        })}
      </nav>
      {/* Mobile bottom bar — inline display removed so Tailwind md:hidden wins */}
      <nav style={{
        position: 'fixed', bottom: 0, left: 0, right: 0, zIndex: 100,
        background: 'var(--bg-panel)', borderTop: '1px solid var(--border)',
        justifyContent: 'space-around', padding: '8px 0 12px',
      }} className="flex md:hidden">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = path.startsWith(href)
          return (
            <Link key={href} href={href} style={{
              display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 4,
              color: active ? 'var(--indigo)' : 'var(--text-muted)',
              textDecoration: 'none', fontSize: 10, fontWeight: 600,
            }}>
              <Icon size={18} />
              {label}
            </Link>
          )
        })}
      </nav>
    </>
  )
}
