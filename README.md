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
- Préparation de brouillons pour Facebook, Instagram, TikTok, X, Threads, YouTube, Telegram et Pinterest.
- Copie des brouillons, bibliothèque et sauvegarde locale des textes saisis.
- Contrôle humain obligatoire : aucune publication automatique.

## Limites importantes avant la connexion IA

Les textes sociaux actuels sont **des préformats construits à partir des titres et extraits RSS**. Ils ne sont pas encore des résumés générés par une IA. Les articles non francophones nécessitent une traduction et une relecture. Le détecteur de liens officiels repère des indices, mais ne certifie jamais une information. Un score élevé ne signifie ni viralité ni véracité.

L'assistant IA est volontairement désactivé tant que le moteur sécurisé n'est pas connecté. Aucune clé API ne doit être placée dans le navigateur. L'intégration Cloudflare Worker/API est une étape distincte, après stabilisation de cette version.

## Collecte et actualisation

- GitHub Actions collecte automatiquement les flux environ toutes les 6 heures.
- Le bouton « Recharger les données » relit les derniers fichiers publiés ; il ne déclenche pas lui-même une nouvelle collecte.
- La file éditoriale est plafonnée à 15 sujets retenus par exécution.
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

Le Radar prépare trois sujets maximum et huit formats sociaux par sujet. Une fonction Cloudflare Pages facultative peut rédiger et traduire les textes avec Workers AI, sans droit de publication. Le modèle configuré est `@cf/zai-org/glm-4.7-flash`.

Pour activer cette fonction :

1. Dans Cloudflare Pages > AutreTrend Studios > Settings > Functions > Bindings, ajouter un binding **Workers AI** nommé `AI`.
2. Dans Cloudflare Pages > Settings > Variables and Secrets, créer le secret `AUTOTREND_AI_TOKEN`.
3. Dans GitHub > Settings > Secrets and variables > Actions, créer `AUTOTREND_AI_URL` avec l'URL HTTPS de la fonction `/api/editorial`, puis `AUTOTREND_AI_TOKEN` avec exactement le même secret.
4. Relancer le workflow Radar. Si les secrets ou le binding manquent, le pipeline conserve ses brouillons de secours et n'interrompt pas la collecte.

Workers AI dispose d'une allocation gratuite de 10 000 Neurons par jour sur le plan Workers Free. Au-delà, le plan gratuit refuse les requêtes supplémentaires; aucun dépassement payant n'est activé automatiquement. Vérifier le compteur d'utilisation Cloudflare avant toute évolution de volume.

L'IA ne publie rien. Chaque texte généré reste marqué comme brouillon, avec relecture humaine obligatoire. Les informations, traductions, dates et noms propres doivent être vérifiés avant publication.
