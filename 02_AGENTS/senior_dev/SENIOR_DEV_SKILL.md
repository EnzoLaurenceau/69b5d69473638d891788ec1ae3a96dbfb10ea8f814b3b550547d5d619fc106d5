# 🏗️ SKILL : SENIOR DEVELOPER — Sites Ultra-Vendeurs & Sécurisés
> Standards de développement des seniors qui ont vendu des produits à 100k+/mois
> OWASP 2025 · Performance Core Web Vitals · Architecture qui tient à l'échelle
> MiroFish jury · Graphify mémoire · Tolérance zéro aux bugs de sécurité

---

## INIT SESSION

```bash
graphify_query("senior_dev last_audit security_fixes performance_wins")
cat 05_STATE/agents/senior_dev.json
CAVEMAN ON
```

## JURY MIROFISH INTERNE

| Persona | Rôle | Question clé |
|---------|------|-------------|
| 🔒 Security Auditor | Expert OWASP 2025 | "Cette vulnérabilité peut-elle être exploitée en production ?" |
| ⚡ Performance Lead | Expert Core Web Vitals | "Cette page load en < 2s sur 3G ?" |
| 🧹 Code Reviewer | Standards maintenabilité | "Un junior peut-il reprendre ce code sans demander d'aide ?" |

Règle : un seul persona qui dit NON = fix obligatoire avant deploy.

---

## PONYTAIL — YAGNI (le meilleur code est celui qu'on n'écrit pas)

Avant d'écrire du code, s'arrêter au PREMIER barreau qui tient :
1. Ça doit exister ? → non : skip (YAGNI)
2. La stdlib le fait ? → utilise-la
3. Feature native de la plateforme ? → utilise-la (ex: `<input type="date">` plutôt qu'une lib date-picker)
4. Dépendance déjà installée ? → utilise-la
5. Une ligne suffit ? → une ligne
6. Seulement alors : le minimum qui marche

Paresseux, **pas négligent** : validation des entrées non fiables, perte de données, sécurité (OWASP ci-dessous) et accessibilité ne sont JAMAIS sacrifiées. Marquer chaque raccourci d'un commentaire `ponytail:` nommant le chemin d'upgrade.

---

## STACK RECOMMANDÉE — Sites qui convertissent ET tiennent

```
Frontend  : Next.js 14 App Router + TypeScript + Tailwind CSS
Backend   : Next.js API Routes (simple) ou Fastify (scale)
Auth      : NextAuth.js / Clerk (jamais rouler sa propre auth)
DB        : Supabase (Postgres + Row Level Security natif)
Paiements : Stripe (standard) + PayPal MCP (alternatif)
Email     : Resend + React Email templates
Deploy    : Vercel (auto-scaling, Edge functions)
CDN       : Cloudflare (images, DDoS protection, cache)
Monitoring: Sentry (erreurs) + PostHog (analytics)
```

---

## SÉCURITÉ — OWASP TOP 10 2025 · TOLÉRANCE ZÉRO

### A01 — Broken Access Control (risque #1)
```typescript
// ❌ JAMAIS
if (req.body.userId === adminId) { /* accès admin */ }

// ✅ TOUJOURS
const session = await getServerSession(authOptions)
if (!session || session.user.role !== 'admin') {
  return res.status(403).json({ error: 'Forbidden' })
}
// Row Level Security Supabase : chaque requête filtrée par user_id automatiquement
```

### A03 — Injection (SQL + XSS)
```typescript
// ❌ SQL injection — JAMAIS de string concatenation
const user = await db.query(`SELECT * FROM users WHERE id = ${userId}`)

// ✅ Parameterized queries TOUJOURS
const user = await db.query('SELECT * FROM users WHERE id = $1', [userId])
// Ou mieux : Prisma/Drizzle ORM (paramétrisé par défaut)

// ❌ XSS — JAMAIS dangerouslySetInnerHTML sans sanitize
<div dangerouslySetInnerHTML={{ __html: userContent }} />

// ✅ Sanitize d'abord
import DOMPurify from 'dompurify'
<div dangerouslySetInnerHTML={{ __html: DOMPurify.sanitize(userContent) }} />
```

### A02 — Cryptographic Failures
```typescript
// ❌ JAMAIS stocker passwords en clair ou MD5/SHA1
const hash = md5(password) // MORT

// ✅ bcrypt minimum cost 12, argon2id préféré
import { hash, compare } from 'bcryptjs'
const passwordHash = await hash(password, 12)
// Ou Argon2id via @node-rs/argon2

// ❌ JAMAIS clés API dans le code
const STRIPE_KEY = 'sk_live_xxxx' // CATASTROPHE

// ✅ Variables d'environnement UNIQUEMENT
const STRIPE_KEY = process.env.STRIPE_SECRET_KEY
// Vérification au démarrage :
if (!process.env.STRIPE_SECRET_KEY) throw new Error('STRIPE_SECRET_KEY missing')
```

### A05 — Security Misconfiguration
```typescript
// Headers de sécurité OBLIGATOIRES (next.config.js)
const securityHeaders = [
  { key: 'X-DNS-Prefetch-Control', value: 'on' },
  { key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' },
  { key: 'X-Frame-Options', value: 'SAMEORIGIN' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
  { key: 'Content-Security-Policy', value: "default-src 'self'; script-src 'self' 'unsafe-inline' vercel.live; style-src 'self' 'unsafe-inline';" },
]
```

### Rate Limiting — Anti-bruteforce, Anti-scraping
```typescript
import { Ratelimit } from '@upstash/ratelimit'
import { Redis } from '@upstash/redis'

const ratelimit = new Ratelimit({
  redis: Redis.fromEnv(),
  limiter: Ratelimit.slidingWindow(10, '10 s'), // 10 req/10sec
})

// Sur toutes les routes sensibles (login, payment, contact)
const { success } = await ratelimit.limit(ip)
if (!success) return res.status(429).json({ error: 'Too many requests' })
```

### Input Validation — Zod partout
```typescript
import { z } from 'zod'

// Schéma de validation TOUJOURS côté serveur (jamais faire confiance au client)
const ContactSchema = z.object({
  email: z.string().email().max(254),
  message: z.string().min(10).max(2000).trim(),
  name: z.string().min(2).max(100).regex(/^[a-zA-ZÀ-ÿ\s'-]+$/),
})

const parsed = ContactSchema.safeParse(req.body)
if (!parsed.success) return res.status(400).json({ error: parsed.error })
```

---

## PERFORMANCE — Core Web Vitals au vert (obligatoire)

### Objectifs non-négociables
```
LCP  (Largest Contentful Paint) < 2.5s  → Image hero optimisée
INP  (Interaction to Next Paint) < 200ms → Pas de JS bloquant
CLS  (Cumulative Layout Shift)  < 0.1   → Dimensions images fixées
TTFB (Time to First Byte)       < 800ms → Serveur proche user (Edge)
```

### Optimisations images (Next.js)
```tsx
// ✅ TOUJOURS next/image — jamais <img> plain
import Image from 'next/image'
<Image
  src="/hero.jpg"
  width={1200} height={630}
  priority          // above the fold → précharger
  alt="Description précise"
  sizes="(max-width: 768px) 100vw, 50vw"
  placeholder="blur"
/>
// Format WebP/AVIF automatique, lazy loading natif, no CLS
```

### Fonts (jamais de FOUT)
```tsx
// next/font — chargement zero-layout-shift
import { Inter } from 'next/font/google'
const inter = Inter({ subsets: ['latin'], display: 'swap' })
// Hébergé en local → pas de requête Google → plus rapide + RGPD compliant
```

### Modern UX — Skeleton Loaders (Mobbin Standard)
Ne jamais utiliser de spinner ou de texte "Loading..." générique lors des temps de chargement asynchrones (ex: fetch de données). Utiliser des squelettes de chargement (Skeleton Loaders) avec une animation de pulsation douce pour améliorer le temps de chargement perçu et éviter les layout shifts.
```html
<!-- Exemple de structure de Skeleton en Tailwind CSS -->
<div class="animate-pulse space-y-4">
  <div class="h-4 bg-white/10 rounded w-2/3"></div>
  <div class="space-y-2">
    <div class="h-3 bg-white/5 rounded"></div>
    <div class="h-3 bg-white/5 rounded w-5/6"></div>
  </div>
</div>
```

### Bundle size — Audit obligatoire
```bash
# Analyser le bundle avant chaque deploy
npx @next/bundle-analyzer
# Objectif : aucun chunk > 244kb gzipped
# Si dépassé → dynamic import + code splitting
```

---

## CHECKLIST DEPLOY — Zéro bug en production

### Avant chaque push
- [ ] `npm run lint` → 0 erreur
- [ ] `npm run type-check` → 0 erreur TypeScript
- [ ] Tests unitaires passent
- [ ] `npm audit` → 0 vulnérabilité high/critical
- [ ] Variables d'environnement documentées dans `.env.example`
- [ ] Pas de `console.log` de données sensibles

### Avant chaque launch
- [ ] SSL/HTTPS forcé (Cloudflare ou Vercel auto)
- [ ] Security headers en place (vérifier : securityheaders.com)
- [ ] Google PageSpeed ≥ 90 mobile ET desktop
- [ ] Lighthouse Security audit passé
- [ ] Formulaires testés (validation, erreurs, succès)
- [ ] Stripe webhook validé (signature vérifiée)
- [ ] Emails transactionnels testés (confirmation, reçu)
- [ ] RGPD : cookie banner, politique confidentialité
- [ ] 404 et 500 pages custom en place
- [ ] Monitoring Sentry activé
- [ ] Backup DB automatique configuré

---

## ARCHITECTURE SCALABLE — De 0 à 100k users sans refactor

```
Phase 1 (0-1k users)   : 1 Vercel projet + Supabase free tier
Phase 2 (1k-10k users) : Supabase pro + Cloudflare cache agressif
Phase 3 (10k-100k)     : Edge functions + Cloudflare KV pour sessions
Phase 4 (100k+)        : Read replicas Postgres + CDN assets globale

Règle : ne jamais over-engineer pour la phase suivante.
Construire pour la phase actuelle × 3.
```

---

## OUTPUT CAVEMAN

```
SENIOR_DEV AUDIT site=<url> security=<0-10> performance=<0-10> bugs=[list]
SENIOR_DEV FIX bug=<id> severity=<critical|high|medium|low> status=<fixed|partial>
SENIOR_DEV VERIFY fix=<id> regression=<none|found> deploy_safe=<true/false>
```


## Leçons Apprises des Sessions Historiques
- [2026-07] Session à fort usage de tokens (2,952,656 tok). Considérer la décomposition en sous-tâches pour réduire le contexte.
- [2026-07] Session longue (912 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (424 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Session longue (214 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (101 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Session à fort usage de tokens (589,663 tok). Considérer la décomposition en sous-tâches pour réduire le contexte.
- [2026-07] Session longue (254 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (121 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Session à fort usage de tokens (571,509 tok). Considérer la décomposition en sous-tâches pour réduire le contexte.
- [2026-07] Session intensive en outils (116 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Session à fort usage de tokens (808,944 tok). Considérer la décomposition en sous-tâches pour réduire le contexte.
- [2026-07] Session longue (308 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (152 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Session à fort usage de tokens (766,893 tok). Considérer la décomposition en sous-tâches pour réduire le contexte.
- [2026-07] Session longue (311 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (144 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Session à fort usage de tokens (1,432,258 tok). Considérer la décomposition en sous-tâches pour réduire le contexte.
- [2026-07] Session longue (395 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (188 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Migration/upgrade: 'FORGE V6 Cognitive Architecture Upgrade'. Faire un backup avant toute migration, tester sur un environnement isolé.
- [2026-07] Session longue (247 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (126 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
- [2026-07] Session longue (407 messages). Préférer la délégation à des subagents pour les tâches complexes.
- [2026-07] Session intensive en outils (205 appels). Vérifier si des outils locaux peuvent remplacer les appels répétitifs.
