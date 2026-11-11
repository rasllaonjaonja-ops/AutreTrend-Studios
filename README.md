# AutreTrend Studios

**Studio éditorial manga & anime — interface française, pensée mobile.**

AutreTrend Studios rassemble une veille RSS, un radar de sujets, un contrôle de provenance et une file de prépublications à relire. Le dépôt est servi comme site statique par Cloudflare Pages, depuis la racine, sans commande de build.

## Fonctions disponibles

- Collecte RSS/Atom planifiée toutes les 6 heures par GitHub Actions.
- Déduplication des URL et regroupement indicatif des articles par sujet.
- Classement explicable : pertinence, fraîcheur, diversité des médias et volume.
- Vérification des liens visibles vers une liste de domaines officiels connus.
- Filtrage éditorial strict : score, fraîcheur, format, présence d'extrait et recoupement.
- Filtres du radar : recherche, source, nombre de médias, score minimum, période, langue et tri.
- Préparation de prépublications françaises distinctes pour Facebook et TikTok uniquement.
- Copie des brouillons, bibliothèque et sauvegarde locale des textes saisis.
- Contrôle humain obligatoire : aucune publication automatique.

## Limites importantes avant la connexion IA

Les prépublications IA sont générées uniquement si le service sécurisé est configuré et si les textes passent les contrôles automatiques. En cas d'échec, le Radar conserve des briefs non publiables et signale le statut de génération. Les articles non francophones doivent être traduits puis relus. Le détecteur sépare les liens officiels candidats des preuves factuelles : un lien vers un domaine connu ne certifie jamais une annonce. Un score élevé ne signifie ni viralité ni véracité.

Aucune clé API n'est placée dans le navigateur. Les secrets sont conservés côté Cloudflare ou GitHub Actions. Facebook et TikTok sont les seules plateformes activées; aucune publication automatique n'est autorisée.

## Collecte et actualisation

- GitHub Actions collecte automatiquement les flux environ toutes les 6 heures.
- Le bouton « Recharger les données » relit les derniers fichiers publiés ; il ne déclenche pas lui-même une nouvelle collecte.
- La file éditoriale est plafonnée à 3 sujets distincts par exécution.
- Les seuils sont définis dans `scripts/verify_sources.py` et peuvent être ajustés après observation des résultats.

## Lancer et déployer

Ouvrir `index.html` dans un navigateur ou déployer le dépôt sur Cloudflare Pages :

- Branche : `main`
- Dossier racine : `/`
- Commande de build : aucune
- Dossier de sortie : `/`

## Contrôles qualité

Le workflow « AutreTrend Quality Check » vérifie les fichiers JSON, les scripts Python, la syntaxe JavaScript intégrée à la page, les identifiants HTML et les ressources locales avant de considérer la mise à jour comme valide.

## Publication

Les contenus sont des brouillons. Vérifier chaque date, nom, studio, casting, annonce, territoire et lien primaire avant publication. La validation et la publication restent manuelles via les outils sociaux de l'utilisateur.


## Rédaction IA sécurisée — activation facultative

Le Radar prépare au maximum trois sujets distincts, chacun décliné en deux textes français : Facebook et TikTok. La fonction Cloudflare Pages utilise d'abord Workers AI (`@cf/zai-org/glm-4.7-flash`), puis son modèle Cloudflare de secours (`@cf/meta/llama-3.3-70b-instruct-fp8-fast`). Si ces deux moteurs échouent, elle peut utiliser Groq comme fournisseur indépendant, uniquement si sa clé est configurée. Aucun texte rejeté n'est accepté et aucune publication automatique n'est possible.

Pour activer cette fonction :

1. Dans Cloudflare Pages > AutreTrend Studios > Settings > Functions > Bindings, ajouter un binding **Workers AI** nommé `AI`.
2. Dans Cloudflare Pages > Settings > Variables and Secrets, créer le secret `AUTOTREND_AI_TOKEN`.
3. Dans GitHub > Settings > Secrets and variables > Actions, créer `AUTOTREND_AI_URL` avec l'URL HTTPS de la fonction `/api/editorial`, puis `AUTOTREND_AI_TOKEN` avec exactement le même secret.
4. Pour ajouter un moteur indépendant de secours, créer dans Cloudflare Pages > Settings > Variables and Secrets le secret `AUTOTREND_GROQ_API_KEY` avec une clé Groq. Le modèle peut être défini par la variable `AUTOTREND_GROQ_MODEL`; à défaut, le système utilise `openai/gpt-oss-20b`.
5. Relancer le workflow Radar. Si Cloudflare renvoie l'erreur de quota `4006`, le Worker saute immédiatement le second modèle Cloudflare et passe au fournisseur indépendant si sa clé est présente. Si cette clé manque, la génération est explicitement rejetée, les brouillons restent non publiables et la collecte RSS continue.

**État de secours :** le code du fournisseur indépendant est prêt, mais il n'est réellement actif que lorsque `AUTOTREND_GROQ_API_KEY` est configurée dans Cloudflare Pages. Le contrôle `GET /api/editorial` expose `groq_fallback_configured` pour vérifier ce point sans révéler la clé.

Groq est un service externe distinct de Cloudflare et peut appliquer des limites ou une tarification selon le compte et le modèle. Vérifier les quotas et les prix affichés dans son compte avant d'ajouter la clé. Ne jamais transmettre la clé dans GitHub, le code source ou le navigateur : elle doit rester un secret Cloudflare.

L'IA ne publie rien. Chaque texte généré reste marqué comme brouillon, avec relecture humaine obligatoire. Les informations, traductions, dates et noms propres doivent être vérifiés avant publication.
