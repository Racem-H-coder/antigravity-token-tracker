const vscode = require('vscode');
const path = require('path');
const os = require('os');
const fs = require('fs');
const { exec } = require('child_process');

let statusBarItem;
let currentPanel = undefined;
let latestStats = null;

function activate(context) {
    // Bouton permanent dans la barre d'état (en bas à droite)
    statusBarItem = vscode.window.createStatusBarItem('antigravity.tokenTracker', vscode.StatusBarAlignment.Right, 1000);
    statusBarItem.name = '⚡ Antigravity Tokens';
    statusBarItem.command = 'antigravityTokenTracker.showMenu';
    statusBarItem.text = '$(pulse) Tokens: ...';
    statusBarItem.tooltip = '📊 Antigravity Token Tracker — Cliquez pour ouvrir le menu et voir les détails';
    statusBarItem.show();
    context.subscriptions.push(statusBarItem);

    const getPaths = () => {
        const homeDir = os.homedir();
        const scriptPath = path.join(homeDir, 'Desktop', 'antigravity-token-tracker', 'scripts', 'tracker.py');
        const dashboardHtml = path.join(homeDir, 'Desktop', 'antigravity-token-tracker', 'dashboard.html');
        return { scriptPath, dashboardHtml };
    };

    // Commande : Ouvrir dans le navigateur externe (Chrome / Edge)
    const openBrowserCmd = vscode.commands.registerCommand('antigravityTokenTracker.openDashboard', () => {
        const { scriptPath, dashboardHtml } = getPaths();
        exec(`python "${scriptPath}" --html`, () => {
            vscode.env.openExternal(vscode.Uri.file(dashboardHtml));
        });
    });

    // Commande : Ouvrir dans un onglet IDE (Webview à côté du code)
    const openWebviewCmd = vscode.commands.registerCommand('antigravityTokenTracker.openWebview', () => {
        const { scriptPath, dashboardHtml } = getPaths();
        
        if (currentPanel) {
            currentPanel.reveal(vscode.ViewColumn.Beside);
        } else {
            currentPanel = vscode.window.createWebviewPanel(
                'antigravityTokenTracker',
                '⚡ Token Tracker Dashboard',
                vscode.ViewColumn.Beside,
                {
                    enableScripts: true,
                    retainContextWhenHidden: true
                }
            );

            currentPanel.onDidDispose(() => {
                currentPanel = undefined;
            }, null, context.subscriptions);
        }

        exec(`python "${scriptPath}" --html`, () => {
            if (fs.existsSync(dashboardHtml) && currentPanel) {
                const htmlContent = fs.readFileSync(dashboardHtml, 'utf8');
                currentPanel.webview.html = htmlContent;
            }
        });
    });

    // Commande : Menu contextuel type QuickPick
    const showMenuCmd = vscode.commands.registerCommand('antigravityTokenTracker.showMenu', async () => {
        const today = latestStats ? (latestStats.today || {}) : {};
        const sum = latestStats ? (latestStats.summary || {}) : {};
        const r5 = latestStats ? (latestStats.rolling_5h_quota || {}) : {};
        const wQuota = latestStats ? (latestStats.week_quota || {}) : {};
        const tQuota = latestStats ? (latestStats.today_quota || {}) : {};
        const qConfig = latestStats ? (latestStats.quota_config || {}) : {};
        const planName = qConfig.active_plan || 'Google AI Pro';
        const proj = latestStats && latestStats.matched_project ? latestStats.matched_project.workspace_name : 'Global';

        const totToday = today.total ? formatTokens(today.total) : 'En cours...';
        const costToday = today.cost_usd ? `$${today.cost_usd.toFixed(2)}` : '$0.00';
        const callsToday = today.calls || 0;
        const cachePct = today.cache_hit_pct !== undefined ? `${today.cache_hit_pct}%` : '0%';

        const rem5h = formatTokens(r5.remaining || 0);
        const remWeek = formatTokens(wQuota.remaining || 0);

        const items = [
            {
                label: `$(history) ⏱️ Reste Instantané (5h) : ${rem5h} (${r5.remaining_pct || 0}% disponible)`,
                description: `Consommé: ${formatTokens(r5.used || 0)} / ${formatTokens(r5.quota || 0)} (${r5.used_pct || 0}% de la limite 5h)`,
                detail: `Fenêtre glissante ${r5.window_start || ''} → ${r5.window_end || ''} (${r5.calls || 0} appels)`,
                action: 'noop'
            },
            {
                label: `$(calendar) 🗓️ Reste Semaine (Weekly) : ${remWeek} (${wQuota.remaining_pct || 0}% disponible)`,
                description: `Consommé: ${formatTokens(wQuota.total || 0)} / ${formatTokens(wQuota.quota || 0)} (${wQuota.used_pct_of_weekly_limit || 0}% de la limite weekly)`,
                detail: `${wQuota.label || 'Semaine en cours'} · Coût hebdo: $${(wQuota.cost_usd || 0).toFixed(2)}`,
                action: 'noop'
            },
            {
                label: `$(graph) 📅 Aujourd'hui : ${totToday} (${tQuota.pct_of_weekly_limit || 0}% du quota weekly)`,
                description: `Coût: ${costToday} · Cache économisé: ${cachePct}`,
                detail: `Input: ${formatTokens(today.input || 0)} · Output: ${formatTokens(today.output || 0)} · Cache: ${formatTokens(today.cached || 0)} (${callsToday} appels)`,
                action: 'noop'
            },
            {
                label: `$(folder) 📁 Workspace Actif : ${proj}`,
                description: latestStats && latestStats.matched_project ? `${formatTokens(latestStats.matched_project.total)} tokens` : '0 tokens',
                action: 'noop'
            },
            {
                label: `$(organization) 💎 Abonnement : ${planName}`,
                description: `5h: ${formatTokens(r5.quota || 0)} · Hebdo: ${formatTokens(wQuota.quota || 0)}`,
                action: 'noop'
            },
            {
                label: '',
                kind: vscode.QuickPickItemKind.Separator
            },
            {
                label: '$(browser) 🌐 Ouvrir le Dashboard dans le Navigateur (Site Web)',
                description: 'Vue complète dans Chrome / Edge',
                action: 'browser'
            },
            {
                label: '$(split-horizontal) 📊 Ouvrir dans un Onglet IDE (Webview)',
                description: 'Afficher le dashboard à côté de votre code',
                action: 'webview'
            },
            {
                label: '$(gear) ⚙️ Changer de Formule d\'Abonnement (Pro, Ultra, Starter, Custom)...',
                description: 'Ajuster vos plafonds 5h et hebdomadaires',
                action: 'changePlan'
            },
            {
                label: '$(sync) 🔄 Rafraîchir les métriques',
                description: 'Recalculer les tokens immédiatement',
                action: 'refresh'
            }
        ];

        const selected = await vscode.window.showQuickPick(items, {
            placeHolder: '⚡ Antigravity Token Tracker — Choisissez une action'
        });

        if (!selected) return;

        if (selected.action === 'browser') {
            vscode.commands.executeCommand('antigravityTokenTracker.openDashboard');
        } else if (selected.action === 'webview') {
            vscode.commands.executeCommand('antigravityTokenTracker.openWebview');
        } else if (selected.action === 'refresh') {
            updateMetrics();
            vscode.window.showInformationMessage('⚡ Métriques de tokens actualisées avec succès.');
        } else if (selected.action === 'changePlan') {
            const planChoices = [
                { label: 'Google AI Pro', description: 'Fenêtre 5h: 75M · Hebdo: 500M ($19.99/mois)' },
                { label: 'Google AI Ultra', description: 'Fenêtre 5h: 250M · Hebdo: 1.5B (Capacité x5)' },
                { label: 'Google AI Starter', description: 'Formule Gratuite / Starter (Hebdo: 100M)' },
                { label: 'Custom', description: 'Personnaliser manuellement vos quotas' }
            ];
            const chosenPlan = await vscode.window.showQuickPick(planChoices, {
                placeHolder: 'Sélectionnez votre formule d\'abonnement Antigravity'
            });
            if (chosenPlan) {
                const { scriptPath } = getPaths();
                exec(`python "${scriptPath}" --set-plan "${chosenPlan.label}"`, (err, stdout) => {
                    if (!err) {
                        updateMetrics();
                        vscode.window.showInformationMessage(`⚡ Formule Antigravity configurée : ${chosenPlan.label}`);
                    }
                });
            }
        }
    });

    function formatTokens(n) {
        if (!n) return '0';
        if (n >= 1000000000) return (n / 1000000000).toFixed(2) + 'B';
        if (n >= 1000000) return (n / 1000000).toFixed(2) + 'M';
        if (n >= 1000) return (n / 1000).toFixed(1) + 'k';
        return n.toString();
    }

    // Mise à jour périodique
    function updateMetrics() {
        const { scriptPath } = getPaths();
        exec(`python "${scriptPath}" --json`, (err, stdout) => {
            if (!err && stdout) {
                try {
                    const data = JSON.parse(stdout);
                    latestStats = data;
                    const today = data.today || {};
                    const total = today.total || 0;
                    const cost = today.cost_usd || 0;
                    const calls = today.calls || 0;
                    const cachePct = today.cache_hit_pct || 0;
                    const proj = data.matched_project ? data.matched_project.workspace_name : 'Global';

                    const r5 = data.rolling_5h_quota || {};
                    const wQuota = data.week_quota || {};
                    const tQuota = data.today_quota || {};
                    const qConfig = data.quota_config || {};
                    const planName = qConfig.active_plan || 'Google AI Pro';

                    const totalFormatted = formatTokens(total);
                    const rem5h = formatTokens(r5.remaining || 0);
                    const remWeek = formatTokens(wQuota.remaining || 0);
                    const used5h = formatTokens(r5.used || 0);
                    const usedWeek = formatTokens(wQuota.total || 0);

                    statusBarItem.text = `$(pulse) 5h: ${rem5h} · Hebdo: ${remWeek} restants`;
                    statusBarItem.tooltip = [
                        `⚡ Antigravity Token Tracker (Quotas Temps Réel)`,
                        `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
                        `⏱️ Reste Instantané (5h) : ${rem5h} / ${formatTokens(r5.quota || 0)} (${r5.remaining_pct || 0}% disponible)`,
                        `   ↳ Consommé 5h        : ${used5h} (${r5.used_pct || 0}% de la limite 5h)`,
                        `🗓️ Reste Semaine (Weekly): ${remWeek} / ${formatTokens(wQuota.quota || 0)} (${wQuota.remaining_pct || 0}% disponible)`,
                        `   ↳ Consommé Semaine   : ${usedWeek} (${wQuota.used_pct_of_weekly_limit || 0}% de la limite weekly)`,
                        `📅 Consommé Aujourd'hui  : ${totalFormatted} (${tQuota.pct_of_weekly_limit || 0}% du quota weekly, ${calls} requêtes)`,
                        `💰 Coût Estimé Jour      : $${cost.toFixed(2)}`,
                        `💾 Taux Économie Cache   : ${cachePct}%`,
                        `📁 Workspace Actif       : ${proj}`,
                        `💎 Formule Abonnement    : ${planName}`,
                        `━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━`,
                        `👉 Cliquez pour ouvrir le Menu & Détails`
                    ].join('\n');
                } catch (e) {}
            }
        });
    }

    updateMetrics();
    const interval = setInterval(updateMetrics, 30000);

    context.subscriptions.push(openBrowserCmd);
    context.subscriptions.push(openWebviewCmd);
    context.subscriptions.push(showMenuCmd);
    context.subscriptions.push({ dispose: () => clearInterval(interval) });
}

function deactivate() {
    if (statusBarItem) statusBarItem.dispose();
    if (currentPanel) currentPanel.dispose();
}

module.exports = {
    activate,
    deactivate
};
