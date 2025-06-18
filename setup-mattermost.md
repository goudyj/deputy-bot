# Configuration Mattermost Local pour Deputy Bot

## 1. Démarrer Mattermost

```bash
docker-compose up -d
```

Attendez quelques minutes que Mattermost démarre, puis accédez à http://localhost:8065

## 2. Configuration initiale de Mattermost

1. **Créer le premier compte admin**
   - Allez sur http://localhost:8065
   - Créez votre compte administrateur

2. **Créer une équipe**
   - Nom: `deputy-test` (ou ce que vous voulez)
   - URL: `deputy-test`

3. **Créer des canaux de test**
   - `dev-bugs` (pour tester la regex `dev-.*`)
   - `support`
   - Gardez `town-square` par défaut

## 3. Créer le bot Deputy

1. **Aller dans System Console**
   - Menu utilisateur > System Console
   - Ou directement: http://localhost:8065/admin_console

2. **Activer les bots**
   - Integrations > Bot Accounts
   - Enable Bot Account Creation: `true`

3. **Créer le bot**
   - Integrations > Bot Accounts > Add Bot Account
   - Username: `deputy`
   - Display Name: `Deputy Bot`
   - Description: `Bot pour gérer les bugs et issues`
   - Role: `Member`
   - **Copiez le token généré !**

4. **Inviter le bot dans les canaux**
   - Allez dans chaque canal (town-square, dev-bugs, support)
   - `/invite @deputy`

## 4. Configuration du bot Deputy

1. **Mettre à jour `.env.local`**
   ```
   MATTERMOST_URL=http://localhost:8065
   MATTERMOST_TOKEN=le_token_du_bot_copié
   MATTERMOST_TEAM_NAME=deputy-test
   MATTERMOST_CHANNELS=town-square,dev-.*,support
   MATTERMOST_BOT_NAME=deputy
   ```

2. **Démarrer le bot**
   ```bash
   cp .env.local .env
   uv sync
   uv run python main.py
   ```

## 5. Tester le bot

Dans un canal où le bot écoute, tapez:
- `@deputy help` - Affiche l'aide
- `@deputy status` - Vérifie le statut
- `@deputy bug Mon application plante` - Test commande bug

## 6. Arrêter l'environnement

```bash
docker-compose down
# Pour supprimer les données:
docker-compose down -v
```