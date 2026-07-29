# BLUEPRINT — CONFORMITÉ JURIDIQUE UNIVERSELLE (legal_compliance)

> Gate OBLIGATOIRE avant DELIVER pour TOUTE création de la Forge (site, landing,
> e-commerce, SaaS, app, chatbot, email, workflow). Enforcement :
> `00_CORE/forge_agents/legal_compliance.py::legal_check()`.

⚠️ **AVERTISSEMENT HONNÊTE** — Ce blueprint vise la conformité MAXIMALE par défaut.
Aucun système ne rend un produit « inattaquable en justice » : le risque zéro
n'existe dans aucun pays. Ce blueprint réduit le risque au minimum raisonnable.
Produits à fort enjeu (santé, finance, assurance, mineurs, données sensibles,
professions réglementées) → **validation par un avocat humain OBLIGATOIRE avant prod**.
Ce document n'est pas un avis juridique.

---

## PRINCIPE — PLUS STRICT DÉNOMINATEUR COMMUN

On ne cible jamais la loi d'UN seul pays. On applique simultanément les régimes
les plus stricts, ce qui couvre par construction la quasi-totalité des marchés :

| Bloc | Textes appliqués par défaut |
|------|------------------------------|
| UE | RGPD 2016/679 · ePrivacy 2002/58 · DSA 2022/2065 · Droits des consommateurs 2011/83 + Omnibus 2019/2161 · Accessibilité EAA 2019/882 (applicable depuis 28/06/2025) · AI Act 2024/1689 |
| France | LCEN 2004-575 art. 6 (mentions légales, hébergeur, logs 1 an) · Code conso (CGV, médiation, garanties) · doctrine CNIL (cookies) |
| USA | CCPA/CPRA (Californie) · CAN-SPAM (emails) · COPPA (<13 ans) · ADA/WCAG (accessibilité) · règles FTC (dark patterns, avis) |
| Canada | PIPEDA · CASL (anti-spam le plus strict au monde : opt-in exprès) |
| UK | UK GDPR · PECR |

**Juridiction cliente inconnue ou multiple → baseline complet ci-dessous, sans exception.**
Conforme UE+FR+Californie+CASL ⇒ couvert presque partout ailleurs.

---

## SOCLE COMMUN (tout produit, tout pays)

1. **Mentions légales / Legal notice / Impressum** — page dédiée + lien footer sur CHAQUE page.
2. **Politique de confidentialité** (RGPD art. 12-14) — responsable de traitement, finalités,
   bases légales, durées de conservation, destinataires, transferts hors UE (clauses types),
   droits (accès, rectification, effacement, portabilité, opposition, limitation),
   droit de réclamation (CNIL/autorité locale), contact DPO si désigné.
3. **Cookies** — bandeau de consentement AVANT tout dépôt non essentiel (ePrivacy + CNIL) :
   refuser aussi facile qu'accepter, granulaire, pas de cases pré-cochées, registre des
   consentements, re-sollicitation ≥ 6 mois après refus, validité consentement ≤ 13 mois.
4. **Hébergeur identifié** (LCEN) — nom, adresse, téléphone.
5. **Contact éditeur** — email + moyen de contact direct visibles.
6. **Accessibilité** — WCAG 2.1 AA minimum (EAA + ADA + RGAA) : alt-texts, contrastes,
   navigation clavier, labels de formulaires. Déclaration d'accessibilité si e-commerce/service.
7. **Minimisation des données** (RGPD art. 5 et 25) — ne collecter QUE le nécessaire,
   privacy by design/by default, cases jamais pré-cochées.
8. **Pas de dark patterns** (DSA + FTC + Omnibus) — pas de faux compteurs, pas de frais cachés,
   annulation aussi simple que souscription.
9. **Licences respectées** — polices, images, icônes, libs OSS : crédits + fichier
   d'attributions ; jamais d'asset sans licence vérifiée.
10. **Sécurité minimale** — HTTPS partout, pas de secrets côté client, notification de
    violation ≤ 72 h (RGPD art. 33), registre des traitements (art. 30) tenu côté client.
11. **Interdit forge** — `localStorage`/`sessionStorage` (règle CLAUDE.md n°4 + privacy) :
    état en PG+Redis côté serveur.
12. **Mineurs** — si le produit peut toucher des <13 ans (COPPA) / <15-16 ans (RGPD) :
    vérification d'âge + consentement parental, sinon exclusion explicite dans les CGU.

## PAR TYPE DE PRODUIT (s'ajoute au socle)

### A. Site vitrine / landing page
- Footer légal complet sur chaque page (template ci-dessous).
- Formulaires de contact : finalité affichée, lien privacy, double opt-in newsletter.
- Carte OpenStreetMap si adresse physique (règle forge n°7) — pas de Google Maps sans consentement cookies.

### B. E-commerce (en plus de A)
- **CGV** accessibles AVANT commande : identité vendeur, caractéristiques, prix, paiement,
  livraison, rétractation, garanties, médiation.
- **Droit de rétractation 14 jours** (UE) + formulaire type de rétractation + exceptions listées.
- **Prix TTC** affichés, devise claire, frais de livraison avant paiement, pas de frais surprise.
- **Bouton de commande** : mention « commande avec obligation de paiement » (directive 2011/83).
- **Garanties légales** : conformité 2 ans (UE) + vices cachés (FR) mentionnées.
- **Médiation de la consommation** : médiateur nommé (nom + site) + lien plateforme ODR
  `https://ec.europa.eu/consumers/odr`.
- **Réductions** : prix de référence = prix le plus bas des 30 derniers jours (Omnibus).
- **Avis clients** : indiquer si/comment ils sont vérifiés (Omnibus/FTC).
- **Facturation** conforme + TVA correcte (OSS si ventes intra-UE) — via PSP (Stripe/PayPal
  gèrent PCI-DSS ; JAMAIS de carte stockée par nous).

### C. SaaS / App (en plus de A)
- **CGU/ToS** : objet, compte, obligations, propriété intellectuelle, résiliation,
  limitation de responsabilité (dans les limites légales), droit applicable + for.
- **DPA** (RGPD art. 28) pour clients B2B + liste des sous-traitants publiée.
- **SLA** si B2B payant.
- **Suppression de compte** effective en self-service + export des données (portabilité).
- **Notification de violation** : procédure 72 h documentée.

### D. Chatbot / produit IA (en plus du type hôte)
- **Transparence AI Act** : l'utilisateur DOIT savoir immédiatement qu'il parle à une IA
  (message d'accueil + mention permanente).
- **Contenu synthétique** marqué comme tel si réaliste (deepfake → marquage obligatoire).
- **Disclaimers** : les réponses ne constituent pas un conseil médical/juridique/financier.
- **RGPD art. 22** : pas de décision à effet juridique entièrement automatisée sans
  intervention humaine possible — aligné règle HITL forge (paiement/booking/suppression = gate humain).
- Logs des conversations : durée de conservation déclarée dans la privacy policy.

### E. Emails & marketing
- **Opt-in exprès préalable** (RGPD + CASL — le plus strict) : jamais d'achat de listes,
  double opt-in recommandé, preuve du consentement conservée.
- Chaque email : identité de l'expéditeur, **adresse postale physique** (CAN-SPAM),
  **lien de désinscription 1 clic** fonctionnel sous 10 jours max.
- Prospection B2C sans consentement = interdite (UE/Canada).

### F. Contenu utilisateur / plateforme (si UGC)
- Point de contact unique + mécanisme de signalement (DSA notice-and-takedown).
- Agent DMCA désigné si audience US.
- Modération documentée dans les CGU.

---

## TEMPLATES SQUELETTES ({{placeholders}} remplis au build via brand_kit + données client)

> Règle : tout placeholder impossible à remplir au build est écrit `TODO-LEGAL` →
> le gate `legal_check()` BLOQUE la livraison tant qu'il en reste un.

### Footer HTML type (chaque page)
```html
<footer>
  <p>© {{year}} {{editor_name}} — {{legal_form}} au capital de {{capital}} €,
     RCS {{rcs_city}} {{siren}}, TVA {{vat_number}}, siège : {{hq_address}}.</p>
  <p>Directeur de la publication : {{publisher_name}} · Contact : {{contact_email}} · {{contact_phone}}</p>
  <p>Hébergeur : {{host_name}}, {{host_address}}, {{host_phone}}</p>
  <nav>
    <a href="/mentions-legales">Mentions légales</a> ·
    <a href="/confidentialite">Politique de confidentialité</a> ·
    <a href="/cookies">Cookies</a>
    {{#ecommerce}} · <a href="/cgv">CGV</a>{{/ecommerce}}
    {{#saas}} · <a href="/cgu">CGU</a>{{/saas}}
    · <a href="/accessibilite">Accessibilité</a>
  </nav>
</footer>
```

### Page « Mentions légales » (sections)
Éditeur (identité complète) → Directeur de publication → Hébergeur → Propriété
intellectuelle → Crédits (images/polices/licences) → Contact → Droit applicable.

### Page « Politique de confidentialité » (sections)
Responsable de traitement → Données collectées + finalités + bases légales (tableau) →
Durées de conservation → Destinataires & sous-traitants → Transferts hors UE →
Droits RGPD + comment les exercer → Réclamation CNIL → Cookies (renvoi) → Contact/DPO.

### Bandeau cookies (spec comportement — pas de dépôt avant choix)
Boutons « Tout accepter » / « Tout refuser » / « Personnaliser » de même taille et
même niveau ; aucun cookie non essentiel avant consentement ; choix mémorisé
(refus 6 mois, accord ≤ 13 mois) ; lien « Gérer mes cookies » permanent au footer.

### Page « CGV » (sections — e-commerce)
Identité vendeur → Produits/prix TTC → Commande (obligation de paiement) → Paiement →
Livraison → Rétractation 14 j + formulaire type → Garanties légales → Responsabilité →
Médiation + ODR → Droit applicable.

### Page « CGU » (sections — SaaS)
Objet → Compte & sécurité → Usage acceptable → Propriété intellectuelle → Données
(renvoi privacy + DPA) → Disponibilité/SLA → Résiliation & réversibilité →
Responsabilité → Modifications → Droit applicable + for.

### Accueil chatbot IA
« 🤖 Je suis un assistant virtuel basé sur l'intelligence artificielle de {{editor_name}}.
Mes réponses sont informatives et ne constituent pas un conseil professionnel. »
(traduit automatiquement dans la langue active — règle forge n°6).

### Footer email marketing
Identité expéditeur + adresse postale physique + « Vous recevez cet email car vous
avez consenti le {{optin_date}} » + lien désinscription 1 clic.

---

## DONNÉES CLIENT REQUISES (à demander AVANT tout build)

Identité : raison sociale, forme juridique, capital, SIREN/SIRET + RCS (ou équivalent
local), TVA intracom, adresse du siège, email + téléphone de contact, directeur de
publication. Infra : hébergeur (nom, adresse, téléphone). E-commerce : médiateur de la
consommation choisi (nom + site). Contexte : juridictions cibles, activité réglementée
O/N, public mineur possible O/N, données sensibles O/N (si OUI → escalade avocat).
**Donnée manquante → `TODO-LEGAL` dans le livrable → DELIVER bloqué. On demande au
user, on n'invente JAMAIS une donnée légale (SIRET, médiateur…).**

---

## GATE & ENFORCEMENT

```
1. BUILD    : les agents génèrent les pages légales depuis les templates ci-dessus
              (contenu long → forge_call FREE tier, jamais dans le contexte Claude).
2. S6.5     : LEGAL CHECK — legal_check(project_path, product_type)
              (entre S6 RE-AUDIT Herald et S7 MIROFISH de la séquence MVP Factory).
3. Blocage  : deliver_ready=False (critique manquante, TODO-LEGAL, localStorage,
              violation) → PAS de DELIVER. Comme Herald grade < C.
4. Jury     : state['legal_grade'] injecté à MiroFish — persona « Legal_Officer »
              (poids 1.0) évalue avec la checklist de CE blueprint ;
              grade < B → -2.0 pts sur le verdict final.
5. Harness  : complète ArtifactType.WEBSITE/EMAIL (harness_engine) — le harness vérifie
              la qualité, legal_check vérifie le droit ; les deux doivent passer.
6. Critère de livraison : legal grade ≥ B ET 0 critique manquante ET 0 violation.
```
