        let currentDraftPath = '';
        let materialsConfig = [];
        let currentDraftVersion = 'all';
        let textsConfig = [];
        let currentMixStrategy = 'group';
        let pollInterval = null;
        let resourceCache = [];
        let duoCache = [];
        let duoPageCache = {};
        let duoAutoRefresh = null;
        let draftTrackMeta = [];
        let exportDraftQueue = [];
        let splitDraftQueue = [];
        let runtimeFeatures = { duo: true, openclaw: true, manga: true };
        let runtimeFeatureFlags = {
            duo: 'DUO_FEATURES_ENABLED',
            openclaw: 'OPENCLAW_FEATURES_ENABLED',
            manga: 'MANGA_FEATURES_ENABLED'
        };
        let runtimeFeatureRequirements = {
            duo: ['DUO_FEATURES_ENABLED'],
            openclaw: ['OPENCLAW_FEATURES_ENABLED'],
            manga: ['MANGA_FEATURES_ENABLED', 'OPENCLAW_FEATURES_ENABLED']
        };
        let currentUserInfo = null;
        let accountOverview = null;
        let activeDraftShell = null;

        const tokenKey = 'vf_token';
        const themeKey = 'vf_theme';
        const workspaceSettingsKey = 'vf_workspace_settings';
        const recentMaterialFoldersKey = 'vf_recent_material_folders';
        let workspaceSettingsConfigCache = null;
        let siteSettingsCache = readInitialSiteSettings();

        function readInitialSiteSettings() {
            const node = document.getElementById('siteSettingsPayload');
            if (!node) return {};
            try {
                return JSON.parse(node.textContent || '{}');
            } catch (error) {
                return {};
            }
        }

        function normalizeSiteSettings(raw = {}) {
            const data = raw && typeof raw === 'object' ? raw : {};
            const meta = data.meta && typeof data.meta === 'object' ? data.meta : {};
            const workspace = data.workspace && typeof data.workspace === 'object' ? data.workspace : {};
            const login = data.login && typeof data.login === 'object' ? data.login : {};
            const locked = data.locked && typeof data.locked === 'object' ? data.locked : {};
            const admin = data.admin && typeof data.admin === 'object' ? data.admin : {};
            const siteName = String(data.site_name || meta.site_name || 'VideoFactory');
            return {
                site_name: siteName,
                title: String(data.site_title || data.title || meta.title || `${siteName} 工作台`),
                keywords: String(data.site_keywords || data.keywords || meta.keywords || 'video,ai,generate'),
                description: String(data.site_description || data.description || meta.description || `${siteName} 工作台与视频生产配置中心`),
                workspace_title: String(data.workspace_title || workspace.title || '工作台'),
                workspace_subtitle: String(
                    data.workspace_subtitle
                    || workspace.subtitle
                    || '左侧切换功能，右侧按页面提示操作。需要草稿的功能会在当前页面内完成选择。'
                ),
                login_title: String(data.login_title || login.title || `登录 ${siteName}`),
                login_subtitle: String(data.login_subtitle || login.subtitle || '登录后继续使用当前工作台。'),
                locked_title: String(data.locked_title || locked.title || '登录后进入工作台'),
                locked_subtitle: String(data.locked_subtitle || locked.subtitle || '登录后继续当前工作台。'),
                admin_title: String(data.admin_title || admin.title || `${siteName} 管理后台`),
                admin_subtitle: String(data.admin_subtitle || admin.subtitle || '集中处理授权、试用额度、CDK、设备绑定和用户检索。')
            };
        }

        function applySiteSettings(raw = {}) {
            siteSettingsCache = normalizeSiteSettings(raw);
            document.title = siteSettingsCache.title;
            const textPairs = [
                ['lockedTitle', siteSettingsCache.locked_title],
                ['lockedSubtitle', siteSettingsCache.locked_subtitle],
                ['loginBrandTitle', siteSettingsCache.login_title],
                ['loginBrandSubtitle', siteSettingsCache.login_subtitle],
                ['workspaceTitle', siteSettingsCache.workspace_title],
                ['workspaceSubtitle', siteSettingsCache.workspace_subtitle]
            ];
            textPairs.forEach(([id, text]) => {
                const node = document.getElementById(id);
                if (node) node.textContent = text;
            });
            return siteSettingsCache;
        }

        async function loadSiteSettings() {
            applySiteSettings(siteSettingsCache);
            try {
                const response = await fetch('/api/site-settings');
                if (!response.ok) throw new Error(`site settings ${response.status}`);
                const data = await response.json();
                applySiteSettings(data);
            } catch (error) {
                console.warn('loadSiteSettings failed', error);
            }
            return siteSettingsCache;
        }

        function inferDraftVersion(value = '') {
            const raw = String(value || '').toLowerCase();
            if (raw.includes('capcut')) return 'capcut';
            if (raw.includes('jianying') || raw.includes('剪映')) return 'jianying';
            return 'all';
        }

        function escapeHtml(value) {
            return String(value ?? '')
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }

        function buildDraftSectionHint(total, limit, noun) {
            if (total <= limit) return `共 ${total} ${noun}`;
            return `共 ${total} ${noun}，默认先显示前 ${limit} 项`;
        }

        function buildDraftCompactToggle(total, limit) {
            if (total <= limit) return '';
            return `<button class="effect-add draft-compact-toggle" type="button" onclick="toggleDraftCompactSection(this)">展开全部</button>`;
        }

        function getMixConsumptionHint(strategy = getSelectedReplaceStrategy()) {
            const hintMap = {
                group: {
                    short: '每个槽位目录每次只取 1 个素材；目录里素材多时，会随批量数量顺序轮换。',
                    detail: '当前不是把同一槽位里的多段视频自动拼进一条成片，而是每次生成为该槽位取 1 个素材。想把目录里的多个视频都用到，就把批量数量开大。'
                },
                mix: {
                    short: '所有槽位共享素材池；每个槽位每次只取 1 个素材，random 会随机抽取，素材多时更适合靠批量数量做裂变。',
                    detail: '当前不是单条成片里自动拼接多个素材，而是每次生成为每个槽位各取 1 个素材。素材池越大、批量数量越高，裂变组合越丰富。'
                },
                partition: {
                    short: '每个分区目录每次只取 1 个素材；同名分区目录里素材多时，会随批量数量顺序轮换。',
                    detail: '当前不是把同一分区目录里的多段视频自动拼到一个槽位里，而是每次生成为该分区取 1 个素材。想覆盖更多素材，同样要靠批量数量推进。'
                }
            };
            return hintMap[strategy] || hintMap.group;
        }

        function toggleDraftCompactSection(button) {
            const section = button?.closest('[data-compact-section]');
            if (!section) return;
            const expanded = section.classList.toggle('is-expanded');
            button.textContent = expanded ? '收起' : '展开全部';
        }

        function renderCompactMaterials(materials = [], limit = 8) {
            const hint = buildDraftSectionHint(materials.length, limit, '个槽位');
            const toggle = buildDraftCompactToggle(materials.length, limit);
            const copy = getMixModeCopy();
            const cards = materials.map((name, index) => {
                const hiddenClass = index >= limit ? ' is-extra' : '';
                return `
                    <div class="material-pill-card${hiddenClass}">
                        <strong>槽位 ${index + 1}</strong>
                        <span>${escapeHtml(name)}</span>
                    </div>
                `;
            }).join('');
            return `
                <div class="strip-head">
                    <h3 id="mixMaterialsTitle">${copy.materialsTitle}</h3>
                    <div class="strip-head-meta">
                        <span id="mixMaterialsDesc">${copy.materialsDesc} ${hint}</span>
                        ${toggle}
                    </div>
                </div>
                <div class="materials-strip materials-strip-vertical" data-compact-section="materials">${cards}</div>
            `;
        }

        function renderCompactTexts(texts = [], limit = 6) {
            const hint = buildDraftSectionHint(texts.length, limit, '段文字');
            const toggle = buildDraftCompactToggle(texts.length, limit);
            const cards = texts.map((item, index) => {
                const defaultValue = item?.default || item || '';
                const hiddenClass = index >= limit ? ' is-extra' : '';
                return `
                    <div class="text-strip-item${hiddenClass}">
                        <label for="text_${index}">第 ${index + 1} 段文字</label>
                        <input type="text" id="text_${index}" value="${escapeHtml(defaultValue)}" placeholder="请输入新文字">
                    </div>
                `;
            }).join('');
            return `
                <div class="materials-strip-card">
                    <div class="strip-head">
                        <h3>草稿文字槽</h3>
                        <div class="strip-head-meta">
                            <span>${hint}</span>
                            ${toggle}
                        </div>
                    </div>
                    <div class="text-strip" data-compact-section="texts">${cards}</div>
                </div>
            `;
        }

        function getWorkspaceSettings() {
            try {
                return JSON.parse(localStorage.getItem(workspaceSettingsKey) || '{}');
            } catch (e) {
                return {};
            }
        }

        function setWorkspaceSettings(patch = {}) {
            const next = Object.assign({}, getWorkspaceSettings(), patch || {});
            localStorage.setItem(workspaceSettingsKey, JSON.stringify(next));
            return next;
        }

        function getWorkspaceSettingsConfigCache() {
            return workspaceSettingsConfigCache && typeof workspaceSettingsConfigCache === 'object'
                ? workspaceSettingsConfigCache
                : {};
        }

        function cacheWorkspaceSettingsConfig(settings = {}) {
            workspaceSettingsConfigCache = settings && typeof settings === 'object' ? settings : {};
            return workspaceSettingsConfigCache;
        }

        function getWorkspacePathDefaults() {
            const settings = getWorkspaceSettingsConfigCache();
            return settings.paths && typeof settings.paths === 'object' ? settings.paths : {};
        }

        function getWorkspaceServiceDefaults() {
            const settings = getWorkspaceSettingsConfigCache();
            return settings.services && typeof settings.services === 'object' ? settings.services : {};
        }

        function syncWorkspacePathInputs() {
            const localSettings = getWorkspaceSettings();
            const paths = getWorkspacePathDefaults();
            const materialDefault = paths.material_folder || '';
            const audioDefault = paths.audio_folder || '';
            const exportDefault = paths.default_export_dir || '';
            const fieldPairs = [
                ['settingsMaterialFolder', materialDefault],
                ['settingsDraftsFolder', paths.drafts_folder || ''],
                ['settingsAudioFolder', audioDefault],
                ['settingsDefaultExportDir', exportDefault]
            ];
            fieldPairs.forEach(([id, value]) => {
                const el = document.getElementById(id);
                if (el && !el.value) el.value = value;
            });
            const materialInput = document.getElementById('folder_path');
            if (materialInput && !materialInput.value) {
                materialInput.value = localSettings.last_materials_root || materialDefault;
            }
            const audioInput = document.getElementById('audio_folder_path');
            if (audioInput && !audioInput.value) {
                audioInput.value = localSettings.last_audio_root || audioDefault;
            }
            const exportInput = document.getElementById('export_dir');
            if (exportInput && !exportInput.value) {
                exportInput.value = exportDefault;
            }
        }

        function getRecentMaterialFolders() {
            try {
                const items = JSON.parse(localStorage.getItem(recentMaterialFoldersKey) || '[]');
                return Array.isArray(items) ? items : [];
            } catch (e) {
                return [];
            }
        }

        function pushRecentMaterialFolder(path) {
            const value = String(path || '').trim();
            if (!value) return;
            const list = getRecentMaterialFolders().filter((item) => item && item !== value);
            list.unshift(value);
            localStorage.setItem(recentMaterialFoldersKey, JSON.stringify(list.slice(0, 6)));
            renderRecentMaterialFolders();
        }

        function useRecentMaterialFolder(index) {
            const list = getRecentMaterialFolders();
            const value = list[index];
            const input = document.getElementById('folder_path');
            if (!value || !input) return;
            input.value = value;
            setWorkspaceSettings({last_materials_root: value});
            updatePrimaryActionState();
        }

        function renderRecentMaterialFolders() {
            const box = document.getElementById('recentMaterialFolders');
            if (!box) return;
            const list = getRecentMaterialFolders();
            if (!list.length) {
                box.innerHTML = '';
                return;
            }
            box.innerHTML = list.map((item, index) => `<button class="recent-folder-chip" type="button" onclick="useRecentMaterialFolder(${index})" title="${item}">${item}</button>`).join('');
        }

        function getToken() {
            return localStorage.getItem(tokenKey) || '';
        }

        function setToken(token) {
            localStorage.setItem(tokenKey, token || '');
        }

        function clearToken() {
            localStorage.removeItem(tokenKey);
        }

        function setAuthMessage(msg, isError = true) {
            const el = document.getElementById('authMsg');
            if (!el) return;
            el.style.color = isError ? '#ef4444' : '#16a34a';
            el.textContent = msg || '';
        }

        async function loadRuntimeFeatures() {
            try {
                const res = await fetch('/api/runtime-features');
                const data = await res.json();
                if (res.ok && data.ok && data.features) {
                    runtimeFeatures = Object.assign({}, runtimeFeatures, data.features);
                    runtimeFeatureFlags = Object.assign({}, runtimeFeatureFlags, data.flags || {});
                    runtimeFeatureRequirements = Object.assign({}, runtimeFeatureRequirements, data.requirements || {});
                }
            } catch (e) {}
            applyRuntimeFeatureVisibility();
            renderCommercialSummary();
        }

        function getRuntimeFlagName(key) {
            return runtimeFeatureFlags[key] || '';
        }

        function getRuntimeRequirementText(key) {
            const items = runtimeFeatureRequirements[key] || [];
            return items.length ? items.join(' + ') : getRuntimeFlagName(key);
        }

        function buildRuntimeSummaryText() {
            const items = [
                `Duo ${runtimeFeatures.duo ? '已开启' : '未开启'}`,
                `AI 漫剧 ${runtimeFeatures.manga ? '已开启' : '未开启'}`,
                `AI 漫剧服务 ${runtimeFeatures.openclaw ? '已开启' : '未开启'}`
            ];
            return items.join(' / ');
        }

        function renderCommercialSummary() {
            const lockedRuntime = document.getElementById('lockedFeatureRuntime');
            const accountFeatureStatus = document.getElementById('accountFeatureStatus');

            const runtimeText = buildRuntimeSummaryText();
            const disabledFlags = [];
            if (!runtimeFeatures.duo) disabledFlags.push(`Duo 资源需 ${getRuntimeRequirementText('duo')}`);
            if (!runtimeFeatures.manga) disabledFlags.push(`AI 漫剧需 ${getRuntimeRequirementText('manga')}`);
            if (!runtimeFeatures.openclaw) disabledFlags.push(`AI 漫剧服务需 ${getRuntimeRequirementText('openclaw')}`);
            const disabledHint = disabledFlags.length
                ? `未开启项：${disabledFlags.join(' / ')}`
                : '当前可选功能均可正常使用。';

            if (lockedRuntime) {
                lockedRuntime.textContent = `${runtimeText}。${disabledHint}`;
            }

            if (accountFeatureStatus) {
                accountFeatureStatus.textContent = `${runtimeText}\n${disabledHint}`;
            }
        }

        function applyRuntimeFeatureVisibility() {
            const mangaNotice = document.getElementById('mangaFeatureNotice');
            const mangaContent = document.getElementById('mangaFeatureContent');
            const mangaSidebarLink = document.getElementById('aiMangaSidebarLink');
            const openclawBtn = document.getElementById('openclawConfigBtn');
            const duoSection = document.getElementById('duoSection');
            const duoNotice = document.getElementById('duoFeatureNotice');
            const duoSidebarLink = document.getElementById('duoSidebarLink');

            if (!runtimeFeatures.manga) {
                if (mangaNotice) {
                    mangaNotice.style.display = 'block';
                    mangaNotice.textContent = `当前还不能使用 AI 漫剧。需要条件：${getRuntimeRequirementText('manga')}。`;
                }
                if (mangaContent) mangaContent.style.display = 'none';
                if (mangaSidebarLink) mangaSidebarLink.classList.add('is-disabled');
            } else {
                if (mangaNotice) mangaNotice.style.display = 'none';
                if (mangaContent) mangaContent.style.display = 'block';
                if (mangaSidebarLink) mangaSidebarLink.classList.remove('is-disabled');
            }

            if (!runtimeFeatures.openclaw && openclawBtn) {
                openclawBtn.style.display = 'none';
            }

            if (!runtimeFeatures.duo) {
                if (duoNotice) {
                    duoNotice.style.display = 'block';
                    duoNotice.textContent = `当前还不能使用 Duo 资源。需要条件：${getRuntimeRequirementText('duo')}。`;
                }
                if (duoSection) duoSection.style.display = 'none';
                if (duoSidebarLink) duoSidebarLink.classList.add('is-disabled');
            } else {
                if (duoNotice) duoNotice.style.display = 'none';
                if (duoSection) duoSection.style.display = 'block';
                if (duoSidebarLink) duoSidebarLink.classList.remove('is-disabled');
            }
        }

        function openAuthModal() {
            const modal = document.getElementById('authModal');
            if (!modal) return;
            modal.classList.add('open');
            modal.style.display = 'flex';
            modal.setAttribute('aria-hidden', 'false');
        }

        function closeAuthModal() {
            const modal = document.getElementById('authModal');
            if (!modal) return;
            modal.classList.remove('open');
            modal.style.display = 'none';
            modal.setAttribute('aria-hidden', 'true');
        }

        function updateWorkspaceDraftBadge() {
            const badge = document.getElementById('workspaceDraftBadge');
            if (!badge) return;
            if (!currentDraftPath) {
                badge.textContent = '当前未选择草稿';
                return;
            }
            const name = currentDraftPath.split(/[\\/]/).filter(Boolean).pop() || currentDraftPath;
            const versionMap = {
                all: '自动识别',
                jianying: '剪映',
                capcut: 'CapCut 国际版'
            };
            badge.textContent = `${versionMap[currentDraftVersion] || '自动识别'} / ${name}`;
        }

        function getActiveWorkspacePanel() {
            return document.querySelector('.workspace-panel.active') || document.querySelector('.workspace-panel');
        }

        function getAllDraftShells() {
            return Array.from(document.querySelectorAll('[data-draft-shell="true"]'));
        }

        function getCurrentDraftShell(scope = null) {
            if (scope?.matches?.('[data-draft-shell="true"]')) return scope;
            return scope?.querySelector?.('[data-draft-shell="true"]') || getActiveWorkspacePanel()?.querySelector?.('[data-draft-shell="true"]') || getAllDraftShells()[0] || null;
        }

        function getDraftElement(role, panel = null) {
            const scope = panel || getCurrentDraftShell(getActiveWorkspacePanel());
            const roleMap = {
                version: '#draftVersionSelect',
                path: '#draft_path',
                status: '#draft_status',
                summary: '#draftDiscoverySummary',
                roots: '#draftRootList',
                list: '#draftDiscoveryList'
            };
            return scope?.querySelector(`[data-draft-role="${role}"]`) || document.querySelector(roleMap[role]);
        }

        function getDraftPickerElements() {
            return {
                modal: document.getElementById('draftPickerModal'),
                version: document.getElementById('draftPickerVersionSelect'),
                summary: document.getElementById('draftPickerSummary'),
                roots: document.getElementById('draftPickerRoots'),
                list: document.getElementById('draftPickerList')
            };
        }

        function isDraftPickerOpen() {
            return !!document.getElementById('draftPickerModal')?.classList.contains('open');
        }

        function openDraftPicker(shell = null) {
            const picker = getDraftPickerElements();
            const targetShell = getCurrentDraftShell(shell);
            activeDraftShell = targetShell;
            if (!picker.modal || !targetShell) return;
            if (picker.version) picker.version.value = currentDraftVersion || 'all';
            picker.modal.classList.add('open');
            picker.modal.setAttribute('aria-hidden', 'false');
            discoverDrafts(targetShell, true);
        }

        function closeDraftPicker() {
            const picker = getDraftPickerElements();
            if (!picker.modal) return;
            picker.modal.classList.remove('open');
            picker.modal.setAttribute('aria-hidden', 'true');
        }

        function getDraftRefreshButtons() {
            return Array.from(document.querySelectorAll('[data-action="refresh-drafts"]'));
        }

        function syncDraftShellValues(message = '') {
            const settings = getWorkspaceSettings();
            getAllDraftShells().forEach((shell) => {
                const versionSelect = getDraftElement('version', shell);
                const pathInput = getDraftElement('path', shell);
                const status = getDraftElement('status', shell);
                if (versionSelect) {
                    versionSelect.value = currentDraftVersion || versionSelect.value || settings.last_draft_version || 'all';
                }
                if (pathInput) {
                    pathInput.value = currentDraftPath || pathInput.value || settings.last_draft_path || '';
                }
                if (status && message) {
                    status.textContent = message;
                }
            });
        }

        function syncEffectsSectionVisibility() {
            const effects = document.getElementById('effects_section');
            const emptyState = document.getElementById('effectsEmptyState');
            if (!effects) return;
            const canShowEffects = !!getToken() && effects.dataset.ready === 'true';
            effects.style.display = canShowEffects ? 'block' : 'none';
            if (emptyState) {
                emptyState.style.display = canShowEffects ? 'none' : 'block';
                if (!canShowEffects) {
                    const copyMap = {
                        'effects-core': '先选择草稿，再继续套用预设和添加基础效果。',
                        'effects-resource': '先选择草稿，再搜索资源库并把资源加入当前效果方案。',
                        'effects-duo': '先选择草稿，再筛选 Duo 分类、搜索资源并应用到当前草稿。'
                    };
                    const currentItem = activeWorkspaceNav?.group === 'effects' ? activeWorkspaceNav?.item : 'effects-core';
                    emptyState.textContent = copyMap[currentItem] || '先选择草稿，再继续使用效果配置、资源库和 Duo 资源。';
                }
            }
            if (!canShowEffects) return;
            const activeBtn = effects.querySelector('.subtab-btn.active');
            const activeTarget = activeBtn?.dataset?.target
                || (activeWorkspaceNav?.group === 'effects' ? WORKSPACE_NAV_CONFIG.effects?.items?.[activeWorkspaceNav.item]?.target : '')
                || 'effects-core';
            activateSecondaryTab('effects_section', activeTarget);
        }

        function toggleProtectedUI(isLoggedIn) {
            const tip = document.getElementById('login_tip');
            const locked = document.getElementById('workbenchLocked');
            const app = document.getElementById('workbenchApp');
            const accountEmpty = document.getElementById('accountEmptyState');
            syncEffectsSectionVisibility();
            if (tip) tip.style.display = isLoggedIn ? 'none' : 'block';
            if (locked) locked.style.display = 'none';
            if (app) {
                app.style.display = 'block';
                app.classList.toggle('is-locked', !isLoggedIn);
            }
            if (accountEmpty) accountEmpty.style.display = 'none';
            updateWorkspaceDraftBadge();
            updatePrimaryActionState();
        }

        function forceLoggedOut(message = '已清除登录状态') {
            clearToken();
            closeDraftPicker();
            updateUserPanel(null);
            setAuthMessage(message, false);
            openAuthModal();
            showWorkspacePanel('panel-materials', 'mix-mode-group-anchor');
        }

        function updatePrimaryActionState() {
            const submitBtn = document.getElementById('submitBtn');
            if (!submitBtn) return;
            const hasToken = !!getToken();
            const draftPath = getDraftElement('path')?.value?.trim();
            const folderPath = document.getElementById('folder_path')?.value?.trim();
            const ready = currentDraftPath && currentDraftPath === draftPath;
            submitBtn.disabled = !(hasToken && draftPath && folderPath && ready);
        }

        function getSelectedReplaceStrategy() {
            return currentMixStrategy || 'group';
        }

        function getPartitionFolderLabel(name, fallbackIndex = 0) {
            const raw = String(name || '').trim();
            if (!raw) return `槽位 ${fallbackIndex + 1}`;
            const plain = raw.replace(/\.[^.\\/]+$/, '').trim();
            return plain || raw;
        }

        function getMixModeCopy(strategy = getSelectedReplaceStrategy()) {
            const copyMap = {
                group: {
                    panelTitle: '按组精准替换',
                    panelSub: '参考草稿确定槽位后，每个槽位按独立素材目录严格对应替换，每次生成每槽只取一个素材。',
                    primaryTitle: '按组精准替换',
                    primaryDesc: '先选参考草稿，再按槽位准备素材目录，最后批量生成。',
                    materialsTitle: '第 3 步：确认草稿槽位顺序',
                    materialsDesc: '已识别槽位，后续目录需要一一对应',
                    folderTitle: '第 4 步：选择素材总目录',
                    folderDesc: '总目录下请按槽位拆分子目录，顺序与草稿槽位保持一致。每个子目录可放多条视频，系统会按批量数量轮换。',
                    advancedTitle: '第 5 步：生成与替换设置',
                },
                mix: {
                    panelTitle: '混剪裂变替换',
                    panelSub: '所有片段共用一个素材池，系统会按规则随机组合生成多条成片，但每次生成每槽只取一个素材。',
                    primaryTitle: '混剪裂变替换',
                    primaryDesc: '先选参考草稿，再选择统一素材池目录，最后批量裂变生成。',
                    materialsTitle: '第 3 步：确认草稿可替换槽位',
                    materialsDesc: '已识别槽位，系统会从同一素材池随机组合',
                    folderTitle: '第 4 步：选择素材池目录',
                    folderDesc: '一个目录即可放入全部候选素材，图片和视频可混放。素材越多，批量裂变空间越大。',
                    advancedTitle: '第 5 步：裂变与高级设置',
                },
                partition: {
                    panelTitle: '分区混剪裂变',
                    panelSub: '按片头、主体、片尾这类分区精准匹配素材，同时保持原始顺序，每次生成每分区只取一个素材。',
                    primaryTitle: '分区混剪裂变',
                    primaryDesc: '先选参考草稿，再按分区准备目录，最后批量生成。',
                    materialsTitle: '第 3 步：确认分区槽位',
                    materialsDesc: '已识别分区槽位，目录名称需与分区保持一致',
                    folderTitle: '第 4 步：选择分区总目录',
                    folderDesc: '总目录下请按分区名称建立子目录，适合片头主体片尾不能混用的场景。每个分区目录可放多条视频轮换。',
                    advancedTitle: '第 5 步：分区高级设置',
                }
            };
            return copyMap[strategy] || copyMap.group;
        }

        function setMixStrategy(strategy = 'group') {
            const next = ['group', 'mix', 'partition'].includes(strategy) ? strategy : 'group';
            currentMixStrategy = next;
            updateMixModeUI();
        }

        function updateMixModeUI() {
            const strategy = getSelectedReplaceStrategy();
            const rootLabelMap = {
                group: '素材总目录',
                mix: '素材池目录',
                partition: '分区总目录'
            };
            const label = document.getElementById('materialsRootLabel');
            if (label) label.textContent = rootLabelMap[strategy] || '素材目录';
            const textIds = {
                panelTitle: 'mixPanelTitle',
                panelSub: 'mixPanelSub',
                primaryTitle: 'mixPrimaryTitle',
                primaryDesc: 'mixPrimaryDesc',
                materialsTitle: 'mixMaterialsTitle',
                materialsDesc: 'mixMaterialsDesc',
                folderTitle: 'mixFolderTitle',
                folderDesc: 'mixFolderDesc',
                advancedTitle: 'mixAdvancedTitle'
            };
            const currentCopy = getMixModeCopy(strategy);
            Object.entries(textIds).forEach(([key, id]) => {
                const el = document.getElementById(id);
                if (el && currentCopy[key]) {
                    el.textContent = currentCopy[key];
                }
            });
            const materialsDesc = document.getElementById('mixMaterialsDesc');
            if (materialsDesc && materialsConfig.length) {
                materialsDesc.textContent = `${currentCopy.materialsDesc} ${buildDraftSectionHint(materialsConfig.length, 8, '个槽位')}`;
            }
            const replaceTypeLabel = document.getElementById('replaceTypeLabel');
            const replaceModeLabel = document.getElementById('replaceModeLabel');
            const replaceMode = document.getElementById('replace_mode');
            const advancedHint = document.getElementById('mixAdvancedHint');
            if (replaceTypeLabel) {
                replaceTypeLabel.textContent = strategy === 'partition' ? '分区素材类型' : '素材类型';
            }
            if (replaceModeLabel) {
                replaceModeLabel.textContent = strategy === 'group' ? '槽位分配方式' : strategy === 'mix' ? '裂变分配方式' : '分区分配方式';
            }
            if (replaceMode) {
                replaceMode.value = strategy === 'mix' ? 'random' : 'order';
            }
            if (advancedHint) {
                advancedHint.textContent = getMixConsumptionHint(strategy).short;
            }

            document.querySelectorAll('[data-mix-panel]').forEach((node) => {
                node.classList.toggle('active', node.getAttribute('data-mix-panel') === strategy);
            });
        }

        function renderMixGuideModal() {
            const copy = getMixModeCopy();
            const sub = document.getElementById('mixGuideSub');
            const content = document.getElementById('mixGuideContent');
            if (sub) {
                sub.textContent = `${copy.primaryTitle}：${copy.primaryDesc}`;
            }
            if (!content) return;

            const slotTips = materialsConfig.length
                ? materialsConfig.map((item, index) => `${index + 1}. ${escapeHtml(getPartitionFolderLabel(item, index))}`).join('<br>')
                : '先选择草稿后，这里会显示当前识别到的槽位名称。';

            const strategy = getSelectedReplaceStrategy();
            const advancedTipMap = {
                group: '适合一组素材严格对应一个槽位，先确认总目录下已经按 01、02、03 这类子目录分好。',
                mix: '适合同一素材池反复裂变，目录里可以同时放图片和视频。',
                partition: '适合多分区模板，每个槽位都要有同名目录，否则后端会直接拦截并提示。'
            };
            const consumption = getMixConsumptionHint(strategy);

            content.innerHTML = [
                `<div><strong>当前模式</strong><br>${escapeHtml(copy.primaryTitle)}</div>`,
                `<div style="margin-top:12px;"><strong>准备方式</strong><br>${escapeHtml(copy.folderDesc)}</div>`,
                `<div style="margin-top:12px;"><strong>实际替换规则</strong><br>${escapeHtml(consumption.detail)}</div>`,
                `<div style="margin-top:12px;"><strong>当前槽位参考</strong><br>${slotTips}</div>`,
                `<div style="margin-top:12px;"><strong>补充提示</strong><br>${escapeHtml(advancedTipMap[strategy] || '')}</div>`
            ].join('');
        }

        function openMixGuideModal() {
            renderMixGuideModal();
            const modal = document.getElementById('mixGuideModal');
            if (!modal) return;
            modal.classList.add('open');
            modal.style.display = 'flex';
            modal.setAttribute('aria-hidden', 'false');
        }

        function closeMixGuideModal() {
            const modal = document.getElementById('mixGuideModal');
            if (!modal) return;
            modal.classList.remove('open');
            modal.style.display = 'none';
            modal.setAttribute('aria-hidden', 'true');
        }

        function updateUserPanel(user) {
            const authPanel = document.getElementById('authPanel');
            const userPanel = document.getElementById('userPanel');
            currentUserInfo = user || null;
            if (user) {
                if (authPanel) authPanel.style.display = 'block';
                if (userPanel) userPanel.style.display = 'block';
                const nameEl = document.getElementById('userName');
                const remainEl = document.getElementById('quotaRemaining');
                const totalEl = document.getElementById('quotaTotal');
                const vipEl = document.getElementById('vipExpire');
                const vipBadge = document.getElementById('vipBadge');
                const refCodeEl = document.getElementById('userRefCode');
                const referrerEl = document.getElementById('userReferrer');
                if (nameEl) nameEl.textContent = user.username || '-';
                if (remainEl) remainEl.textContent = user.remaining ?? 0;
                if (totalEl) totalEl.textContent = user.total_generated ?? 0;
                if (vipEl) vipEl.textContent = user.vip_expire_at ? new Date(user.vip_expire_at).toLocaleString() : '-';
                if (refCodeEl) refCodeEl.textContent = user.ref_code || '-';
                if (referrerEl) referrerEl.textContent = user.referrer_id ? `已绑定上级 #${user.referrer_id}` : '未绑定上级';
                const copyBtn = document.getElementById('copyRefCodeBtn');
                if (copyBtn) copyBtn.disabled = !user.ref_code;
                if (vipBadge) {
                    vipBadge.textContent = user.is_vip ? 'VIP' : '普通用户';
                    vipBadge.style.background = user.is_vip ? '#dbeafe' : '#e2e8f0';
                    vipBadge.style.color = user.is_vip ? '#1d4ed8' : '#475569';
                }
                loadLicenseStatus();
                loadPointsOverview();
                closeAuthModal();
                if (document.getElementById('workbenchApp')) {
                    showWorkspacePanel('panel-account');
                }
            } else {
                accountOverview = null;
                if (authPanel) authPanel.style.display = 'block';
                if (userPanel) userPanel.style.display = 'none';
                const aiKeySelect = document.getElementById('ai_key_id');
                if (aiKeySelect) aiKeySelect.innerHTML = '<option value="">自动选择可用账号</option>';
                const licenseStatus = document.getElementById('licenseStatus');
                if (licenseStatus) licenseStatus.textContent = '请登录后查看授权状态。';
                const pointsLogList = document.getElementById('pointsLogList');
                if (pointsLogList) pointsLogList.textContent = '登录后查看最近积分流水。';
                const checkinActionMsg = document.getElementById('checkinActionMsg');
                if (checkinActionMsg) checkinActionMsg.textContent = '';
                const copyBtn = document.getElementById('copyRefCodeBtn');
                if (copyBtn) copyBtn.disabled = true;
            }
            toggleProtectedUI(!!user);
            renderCommercialSummary();
        }

        function renderPointsLogList(items = []) {
            const box = document.getElementById('pointsLogList');
            if (!box) return;
            if (!items.length) {
                box.textContent = '最近还没有积分记录。';
                return;
            }
            box.innerHTML = `<div class="points-log-list">${items.map((item) => {
                const change = Number(item.change || 0);
                const changeText = change > 0 ? `+${change}` : `${change}`;
                const changeClass = change >= 0 ? 'plus' : 'minus';
                const timeText = item.created_at ? new Date(item.created_at).toLocaleString() : '-';
                const remainText = item.remaining_after ?? '-';
                return `<div class="points-log-item">
                    <div class="points-log-head">
                        <strong>${item.reason_label || item.reason || '积分变动'}</strong>
                        <span class="points-log-change ${changeClass}">${changeText}</span>
                    </div>
                    <div class="points-log-meta">时间：${timeText}<br>变动后剩余：${remainText}</div>
                </div>`;
            }).join('')}</div>`;
        }

        function renderPointsOverview() {
            const overview = accountOverview || {};
            const checkedIn = !!overview.checked_in_today;
            const statusText = document.getElementById('checkinStatusText');
            const streakEl = document.getElementById('checkinStreak');
            const rewardEl = document.getElementById('checkinRewardValue');
            const gainEl = document.getElementById('pointsTodayGain');
            const costEl = document.getElementById('pointsTodayCost');
            const actionMsg = document.getElementById('checkinActionMsg');
            const checkinBtn = document.getElementById('dailyCheckinBtn');
            if (statusText) statusText.textContent = checkedIn ? '今日已签到' : '今日未签到';
            if (streakEl) streakEl.textContent = overview.streak_days ?? 0;
            if (rewardEl) rewardEl.textContent = overview.checkin_reward ?? 0;
            if (gainEl) gainEl.textContent = overview.today_gain ?? 0;
            if (costEl) costEl.textContent = overview.today_cost ?? 0;
            if (checkinBtn) {
                checkinBtn.disabled = !currentUserInfo || checkedIn;
                checkinBtn.textContent = checkedIn ? '今日已签到' : '立即签到';
            }
            if (actionMsg && currentUserInfo) {
                actionMsg.textContent = checkedIn
                    ? `今天已完成签到，连续签到 ${overview.streak_days ?? 0} 天。`
                    : `今天签到可领取 ${overview.checkin_reward ?? 0} 奖励值。服务器日期：${overview.server_day || '-'}`;
            }
            renderPointsLogList(overview.recent_logs || []);
            renderCommercialSummary();
        }

        async function loadPointsOverview() {
            if (!getToken()) {
                accountOverview = null;
                renderPointsOverview();
                return;
            }
            try {
                const res = await authFetch('/api/user/points/overview');
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || '积分信息读取失败');
                accountOverview = data.overview || null;
            } catch (e) {
                const actionMsg = document.getElementById('checkinActionMsg');
                if (actionMsg) actionMsg.textContent = `积分信息读取失败：${e.message || e}`;
            }
            renderPointsOverview();
        }

        async function runDailyCheckin() {
            const actionMsg = document.getElementById('checkinActionMsg');
            if (!getToken()) {
                if (actionMsg) actionMsg.textContent = '请先登录后再签到。';
                return;
            }
            const checkinBtn = document.getElementById('dailyCheckinBtn');
            if (checkinBtn) checkinBtn.disabled = true;
            if (actionMsg) actionMsg.textContent = '正在签到，请稍候...';
            try {
                const res = await authFetch('/api/user/checkin', { method: 'POST' });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || '签到失败');
                accountOverview = data.overview || accountOverview;
                if (data.overview?.quota && currentUserInfo) {
                    currentUserInfo = Object.assign({}, currentUserInfo, data.overview.quota);
                    updateUserPanel(currentUserInfo);
                    return;
                }
                if (actionMsg) actionMsg.textContent = data.message || '签到成功';
            } catch (e) {
                if (actionMsg) actionMsg.textContent = e.message || String(e);
            } finally {
                renderPointsOverview();
            }
        }

        function buildDeviceFingerprint() {
            const raw = [
                navigator.userAgent || '',
                navigator.language || '',
                screen.width || '',
                screen.height || '',
                Intl.DateTimeFormat().resolvedOptions().timeZone || ''
            ].join('|');
            let hash = 0;
            for (let i = 0; i < raw.length; i += 1) {
                hash = ((hash << 5) - hash) + raw.charCodeAt(i);
                hash |= 0;
            }
            return `web-${Math.abs(hash)}`;
        }

        async function loadLicenseStatus() {
            const statusEl = document.getElementById('licenseStatus');
            if (!statusEl || !getToken()) return;
            statusEl.textContent = '正在查看授权状态...';
            try {
                const res = await authFetch('/api/license/status');
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '读取失败');
                }
                const items = Array.isArray(data.items) ? data.items : [];
                if (!items.length) {
                    statusEl.textContent = '当前账号还没有激活授权。';
                    return;
                }
                statusEl.textContent = items.map((item) => {
                    const expire = item.expire_at ? new Date(item.expire_at).toLocaleString() : '未设置';
                    const devices = Array.isArray(item.devices) ? item.devices.length : 0;
                    return `卡类型：${item.card_type || '-'} | 到期：${expire} | 设备：${devices}/${item.device_limit || 1} | 转移剩余：${item.transfer_times_left || 0}`;
                }).join('\n');
            } catch (e) {
                statusEl.textContent = `读取授权状态失败：${e.message || e}`;
            }
        }

        async function copyRefCode() {
            const code = document.getElementById('userRefCode')?.textContent?.trim();
            if (!code || code === '-') {
                notify('当前账号还没有可复制的邀请码。', 'warn');
                return;
            }
            try {
                await navigator.clipboard.writeText(code);
                notify('邀请码已复制。', 'success');
            } catch (e) {
                notify('复制失败，请手动复制。', 'warn');
            }
        }

        async function activateLicense() {
            const code = document.getElementById('licenseCodeInput')?.value?.trim().toUpperCase();
            const statusEl = document.getElementById('licenseStatus');
            if (!getToken()) {
                if (statusEl) statusEl.textContent = '请先登录后再激活授权。';
                return;
            }
            if (!code) {
                if (statusEl) statusEl.textContent = '请先输入授权码。';
                return;
            }
            if (statusEl) statusEl.textContent = '授权激活中，请稍候...';
            try {
                const res = await authFetch('/api/license/activate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        code,
                        device_fingerprint: buildDeviceFingerprint(),
                        device_label: 'Web Workspace'
                    })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '激活失败');
                }
                if (statusEl) {
                    const expire = data.expire_at ? new Date(data.expire_at).toLocaleString() : '-';
                    statusEl.textContent = `激活成功\n到期时间：${expire}\n转移剩余：${data.transfer_times_left || 0}`;
                }
                await loadUserInfo();
            } catch (e) {
                if (statusEl) statusEl.textContent = `激活失败：${e.message || e}`;
            }
        }

        async function authFetch(url, options = {}) {
            const opts = options || {};
            opts.headers = opts.headers || {};
            const token = getToken();
            if (token) {
                opts.headers['Authorization'] = `Bearer ${token}`;
            }
            return fetch(url, opts);
        }

        const effectsState = {
            video_effects: [],
            video_animations: [],
            transitions: [],
            masks: [],
            backgrounds: [],
            video_keyframes: [],
            text_animations: [],
            text_bubbles: [],
            text_effects: [],
            audio_effects: [],
            audio_fades: [],
            audio_keyframes: []
        };
        const duoState = {
            text_templates: [],
            video_effects: [],
            transitions: [],
            face_effects: [],
            stickers: []
        };
        const presetMap = {
            vintage_shake: {
                video: {
                    filters: [{type: '复古', intensity: 70}],
                    effects: [{type: '轻微抖动'}],
                    animations: [{type: 'In', name: '弹跳', duration: 0.6}],
                    transitions: [{type: '淡入淡出', duration: 0.5}]
                },
                text: {animations: [{type: 'TextIntro', name: '打字'}]}
            },
            vlog_fresh: {
                video: {
                    filters: [{type: '清新', intensity: 60}],
                    effects: [],
                    animations: [{type: 'In', name: '淡入', duration: 0.4}],
                    transitions: [{type: '滑动', duration: 0.4}]
                }
            },
            cinema: {
                video: {
                    filters: [{type: '胶片', intensity: 80}],
                    effects: [{type: '朦胧'}],
                    animations: [{type: 'In', name: '缩放', duration: 0.6}]
                }
            }
        };

        function parseMaybeJson(raw) {
            if (!raw) return null;
            try { return JSON.parse(raw); } catch (e) { return null; }
        }

        function parseIndexes(raw) {
            if (!raw) return null;
            const parts = raw.split(',').map(v => parseInt(v.trim(), 10)).filter(v => !isNaN(v));
            return parts.length ? parts : null;
        }

        function setToolResult(id, message) {
            const el = document.getElementById(id);
            if (el) el.textContent = message || '';
        }

        function renderAiPromptKeyOptions(items = []) {
            const select = document.getElementById('ai_key_id');
            if (!select) return;
            const activeItems = items.filter((item) => item.is_active !== false);
            select.innerHTML = ['<option value="">自动选择可用账号</option>']
                .concat(activeItems.map((item) => `<option value="${item.id}">${item.key_name || item.provider_code || ('Key #' + item.id)}</option>`))
                .join('');
        }

        async function discoverDrafts(targetShell = null, renderInModal = isDraftPickerOpen()) {
            const shell = getCurrentDraftShell(targetShell || activeDraftShell || getActiveWorkspacePanel());
            const picker = getDraftPickerElements();
            const summary = renderInModal ? picker.summary : getDraftElement('summary', shell);
            const rootList = renderInModal ? picker.roots : getDraftElement('roots', shell);
            const list = renderInModal ? picker.list : getDraftElement('list', shell);
            const version = renderInModal
                ? (picker.version?.value || getDraftElement('version', shell)?.value || currentDraftVersion || 'all')
                : (getDraftElement('version', shell)?.value || currentDraftVersion || 'all');
            const activePath = getDraftElement('path', shell)?.value?.trim() || currentDraftPath || '';
            if (!summary || !rootList || !list) return;
            if (!getToken()) {
                summary.textContent = '请先登录后查看本机草稿。';
                rootList.innerHTML = '';
                rootList.style.display = 'none';
                list.innerHTML = '<div class="tool-result">登录后可自动发现剪映与国际版草稿。</div>';
                return;
            }
            summary.textContent = '正在查找本机草稿...';
            list.innerHTML = '<div class="tool-result">正在查找本机草稿...</div>';
            try {
                const res = await authFetch('/api/drafts/discover?limit=20');
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '草稿扫描失败');
                }
                const roots = Array.isArray(data.roots) ? data.roots : [];
                const drafts = Array.isArray(data.drafts) ? data.drafts : [];
                const filteredDrafts = drafts.filter((item) => version === 'all' || inferDraftVersion(`${item.source} ${item.path}`) === version);
                rootList.innerHTML = '';
                rootList.style.display = 'none';
                if (!filteredDrafts.length) {
                    summary.textContent = '暂未发现可用草稿。';
                    list.innerHTML = '<div class="tool-result">暂未发现可用草稿。</div>';
                    window.__vfDiscoveredDrafts = [];
                    return;
                }
                const visibleDrafts = renderInModal ? filteredDrafts : filteredDrafts.slice(0, 3);
                summary.textContent = renderInModal
                    ? `当前已发现 ${filteredDrafts.length} 个草稿，选择后会自动带回当前模块。`
                    : (filteredDrafts.length > visibleDrafts.length
                        ? `当前模块已发现 ${filteredDrafts.length} 个草稿，默认先展示最近 ${visibleDrafts.length} 个。`
                        : `当前模块已发现 ${filteredDrafts.length} 个最近草稿，可直接选择。`);
                list.innerHTML = visibleDrafts.map((item, idx) => `
                    <div class="draft-item ${activePath && activePath === item.path ? 'active' : ''}" data-draft-index="${idx}" role="button" tabindex="0">
                        <div class="draft-item-head"><strong>${item.name || '未命名草稿'}</strong><span class="draft-use-tag">点击即用</span></div>
                        <div class="draft-meta">来源：${item.source || '-'}\n更新时间：${new Date(item.updated_at).toLocaleString()}\n路径：${item.path}</div>
                    </div>
                `).join('');
                if (!renderInModal && filteredDrafts.length > visibleDrafts.length) {
                    list.innerHTML += `<div class="draft-more-note">其余 ${filteredDrafts.length - visibleDrafts.length} 个草稿已收起，点击“选择草稿”可查看完整列表。</div>`;
                }
                window.__vfDiscoveredDrafts = visibleDrafts;
                list.querySelectorAll('.draft-item').forEach((node) => {
                    const draftIndex = parseInt(node.getAttribute('data-draft-index') || '-1', 10);
                    if (Number.isNaN(draftIndex) || draftIndex < 0) return;
                    node.addEventListener('click', () => useDraftFromDiscovery(draftIndex));
                    node.addEventListener('keydown', (event) => {
                        if (event.key === 'Enter' || event.key === ' ') {
                            event.preventDefault();
                            useDraftFromDiscovery(draftIndex);
                        }
                    });
                });
            } catch (e) {
                summary.textContent = `草稿扫描失败：${e.message || e}`;
                rootList.style.display = 'none';
                list.innerHTML = '<div class="tool-result">草稿扫描失败，请稍后重试。</div>';
            }
        }

        async function useDraftFromDiscovery(idx) {
            const drafts = window.__vfDiscoveredDrafts || [];
            const item = drafts[idx];
            if (!item) return;
            const shell = getCurrentDraftShell(activeDraftShell || getActiveWorkspacePanel());
            const input = getDraftElement('path', shell);
            const version = inferDraftVersion(`${item.source} ${item.path}`);
            if (input) input.value = item.path;
            currentDraftPath = item.path;
            currentDraftVersion = version !== 'all' ? version : (currentDraftVersion || 'all');
            syncDraftShellValues();
            await loadDraftInfo();
            closeDraftPicker();
            discoverDrafts(shell, false);
        }

        function applyManualDraftPath() {
            const manualInput = document.getElementById('draft_path_manual');
            const draftInput = getDraftElement('path');
            const nextPath = manualInput?.value?.trim();
            if (!draftInput || !nextPath) return;
            draftInput.value = nextPath;
            loadDraftInfo();
        }

        function buildAiDraft() {
            const topic = document.getElementById('ai_topic')?.value?.trim();
            const style = document.getElementById('ai_style')?.value || '产品种草';
            const duration = parseInt(document.getElementById('ai_duration')?.value || '30', 10);
            const points = document.getElementById('ai_points')?.value?.trim();
            if (!topic) {
                setToolResult('ai_result', '请先填写主题。');
                return;
            }
            const pointList = points ? points.split(/[,，]/).map(v => v.trim()).filter(Boolean) : [];
            const opening = style === '剧情反转' ? '先抛反差，再揭示主卖点。' : style === '教程演示' ? '先给结果，再拆步骤。' : '先抓注意力，再快速抛卖点。';
            const lines = [
                `主题：${topic}`,
                `风格：${style} / 目标时长：${duration} 秒`,
                `开场策略：${opening}`,
                `内容结构：${Math.max(1, Math.round(duration / 5))} 个画面段落，前 3 秒完成吸引点。`,
                `卖点顺序：${pointList.length ? pointList.join(' -> ') : '主痛点 -> 解决方案 -> 行动召唤'}`,
                `字幕建议：每句控制在 12-18 字，重点词放在前半句。`,
                `收尾动作：落到“立即试用 / 立即购买 / 进入下一步”。`
            ];
            setToolResult('ai_result', lines.join('\n'));
        }

        async function runAiGenerate() {
            const topic = document.getElementById('ai_topic')?.value?.trim();
            const style = document.getElementById('ai_style')?.value || '产品种草';
            const duration = document.getElementById('ai_duration')?.value || '30';
            const points = document.getElementById('ai_points')?.value?.trim() || '';
            const keyId = parseInt(document.getElementById('ai_key_id')?.value || '0', 10);
            if (!getToken()) {
                setToolResult('ai_result', '请先登录后再使用 AI 生成功能。');
                return;
            }
            if (!topic) {
                setToolResult('ai_result', '请先填写主题。');
                return;
            }
            if (!keyId) {
                buildAiDraft();
                setToolResult('ai_result', `${document.getElementById('ai_result')?.textContent || ''}\n\n未选择可用账号，已先用本地内容建议兜底。`);
                return;
            }
            setToolResult('ai_result', '正在生成内容，请稍候...');
            try {
                const prompt = `请为以下短视频生成创作脚本。\n主题：${topic}\n风格：${style}\n时长：${duration} 秒\n卖点：${points || '未提供'}\n输出：标题、3-6个镜头、字幕文案、收尾动作。`;
                const res = await authFetch('/api/ai/generate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        key_id: keyId,
                        task_type: 'text',
                        prompt,
                        max_tokens: 800
                    })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || data.message || 'AI 生成失败');
                }
                const output = data.text || data.content || data.result || JSON.stringify(data, null, 2);
                setToolResult('ai_result', typeof output === 'string' ? output : JSON.stringify(output, null, 2));
            } catch (e) {
                buildAiDraft();
                setToolResult('ai_result', `${document.getElementById('ai_result')?.textContent || ''}\n\nAI 生成没有完成，已先切回本地建议：${e.message || e}`);
            }
        }

        function buildClipTunePlan() {
            const indexesRaw = document.getElementById('clip_indexes')?.value?.trim();
            const indexes = parseIndexes(indexesRaw) || [];
            const rhythm = document.getElementById('clip_rhythm')?.value || '稳态推进';
            const captionLimit = parseInt(document.getElementById('clip_caption_limit')?.value || '16', 10);
            const trimHead = !!document.getElementById('clip_trim_head')?.checked;
            const captionClean = !!document.getElementById('clip_caption_clean')?.checked;
            const speedMin = parseFloat(document.getElementById('clip_speed_min')?.value || '0');
            const speedMax = parseFloat(document.getElementById('clip_speed_max')?.value || '0');
            const scaleMin = parseFloat(document.getElementById('clip_scale_min')?.value || '0');
            const scaleMax = parseFloat(document.getElementById('clip_scale_max')?.value || '0');
            const posX = parseFloat(document.getElementById('clip_pos_x')?.value || '0');
            const posY = parseFloat(document.getElementById('clip_pos_y')?.value || '0');
            const rotation = parseFloat(document.getElementById('clip_rotation')?.value || '0');
            const mirrorH = !!document.getElementById('clip_mirror_horizontal')?.checked;
            const mirrorV = !!document.getElementById('clip_mirror_vertical')?.checked;
            const shakeInterval = parseFloat(document.getElementById('clip_shake_interval')?.value || '0');
            const shakeMaxKeys = parseInt(document.getElementById('clip_shake_max_keys')?.value || '0', 10);
            const shakeX = parseFloat(document.getElementById('clip_shake_x')?.value || '0');
            const shakeY = parseFloat(document.getElementById('clip_shake_y')?.value || '0');
            const lines = [
                `片段范围：${indexes.length ? indexes.join(', ') : '未指定，将按全部片段处理'}`,
                `节奏策略：${rhythm}`,
                `字幕长度：建议单句不超过 ${captionLimit} 字`,
                `默认槽时长：${trimHead ? '按默认槽时长裁剪并压住片头空白' : '保留当前槽时长'}`,
                `字幕整理：${captionClean ? '清理口头语、重复语气词' : '保留原始口播表达'}`,
                `随机变速：${speedMin && speedMax ? `${speedMin}x ~ ${speedMax}x` : '未启用'}`,
                `偏移缩放旋转：缩放 ${scaleMin || 0} ~ ${scaleMax || 0} / 偏移X ${posX || 0} / 偏移Y ${posY || 0} / 旋转 ${rotation || 0}`,
                `镜像：${mirrorH ? '随机左右镜像' : '不镜像'}${mirrorV ? ' + 随机上下翻转' : ''}`,
                `摇晃关键帧：${shakeX || shakeY ? `间隔 ${shakeInterval}s / 最多 ${shakeMaxKeys} 个 / 强度 X:${shakeX} Y:${shakeY}` : '未启用'}`,
                `执行顺序：先按默认槽位做裁剪，再处理变速与位移，最后追加摇晃关键帧。`
            ];
            setToolResult('clip_result', lines.join('\n'));
        }

        function buildMicroAdjustPayload() {
            const indexes = parseIndexes(document.getElementById('clip_indexes')?.value?.trim()) || [];
            const speedMin = parseFloat(document.getElementById('clip_speed_min')?.value || '');
            const speedMax = parseFloat(document.getElementById('clip_speed_max')?.value || '');
            const scaleMin = parseFloat(document.getElementById('clip_scale_min')?.value || '');
            const scaleMax = parseFloat(document.getElementById('clip_scale_max')?.value || '');
            const posX = parseFloat(document.getElementById('clip_pos_x')?.value || '');
            const posY = parseFloat(document.getElementById('clip_pos_y')?.value || '');
            const rotation = parseFloat(document.getElementById('clip_rotation')?.value || '');
            const mirrorHorizontal = !!document.getElementById('clip_mirror_horizontal')?.checked;
            const mirrorVertical = !!document.getElementById('clip_mirror_vertical')?.checked;
            const shakeInterval = parseFloat(document.getElementById('clip_shake_interval')?.value || '');
            const shakeMaxKeys = parseInt(document.getElementById('clip_shake_max_keys')?.value || '0', 10);
            const shakeX = parseFloat(document.getElementById('clip_shake_x')?.value || '');
            const shakeY = parseFloat(document.getElementById('clip_shake_y')?.value || '');
            return {
                indexes,
                rhythm: document.getElementById('clip_rhythm')?.value || '稳态推进',
                caption_limit: parseInt(document.getElementById('clip_caption_limit')?.value || '16', 10),
                trim_head: !!document.getElementById('clip_trim_head')?.checked,
                caption_clean: !!document.getElementById('clip_caption_clean')?.checked,
                speed: {
                    min: Number.isFinite(speedMin) ? speedMin : undefined,
                    max: Number.isFinite(speedMax) ? speedMax : undefined
                },
                transform: {
                    scale_min: Number.isFinite(scaleMin) ? scaleMin : undefined,
                    scale_max: Number.isFinite(scaleMax) ? scaleMax : undefined,
                    pos_x: Number.isFinite(posX) ? posX : undefined,
                    pos_y: Number.isFinite(posY) ? posY : undefined,
                    rotation: Number.isFinite(rotation) ? rotation : undefined
                },
                mirror: {
                    horizontal: mirrorHorizontal,
                    vertical: mirrorVertical
                },
                shake: {
                    interval: Number.isFinite(shakeInterval) ? shakeInterval : undefined,
                    max_keys: Number.isFinite(shakeMaxKeys) && shakeMaxKeys > 0 ? shakeMaxKeys : undefined,
                    intensity_x: Number.isFinite(shakeX) ? shakeX : undefined,
                    intensity_y: Number.isFinite(shakeY) ? shakeY : undefined
                }
            };
        }

        function applyClipSpeedPreset(mode) {
            const minInput = document.getElementById('clip_speed_min');
            const maxInput = document.getElementById('clip_speed_max');
            if (!minInput || !maxInput) return;
            if (mode === 'slow') {
                minInput.value = '0.75';
                maxInput.value = '0.95';
            } else if (mode === 'fast') {
                minInput.value = '1.05';
                maxInput.value = '1.3';
            } else {
                minInput.value = '0.8';
                maxInput.value = '1.25';
            }
            buildClipTunePlan();
        }

        async function applyClipTuneToDraft() {
            const draftPath = getDraftElement('path')?.value?.trim();
            const exportPath = document.getElementById('export_dir')?.value?.trim();
            const exportFormat = document.getElementById('export_format')?.value || 'mp4';
            const microAdjust = buildMicroAdjustPayload();
            if (!getToken()) {
                setToolResult('clip_result', '请先登录后再应用微调。');
                return;
            }
            if (!draftPath || !currentDraftPath || currentDraftPath !== draftPath) {
                setToolResult('clip_result', '请先读取当前草稿，再应用微调。');
                return;
            }
            setToolResult('clip_result', '正在应用微调，请稍候...');
            try {
                const res = await authFetch('/api/micro-adjust', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        draft_path: draftPath,
                        export_path: exportPath || null,
                        export_format: exportFormat,
                        micro_adjust: microAdjust
                    })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '微调失败');
                }
                const summary = data.summary || {};
                const lines = [
                    '微调已完成。',
                    `草稿：${data.draft_name || summary.draft_name || '已更新当前草稿'}`,
                    summary.export_format ? `导出格式：${summary.export_format}` : '导出格式：未指定',
                    summary.warnings && summary.warnings.length ? `警告：${summary.warnings.join(' | ')}` : '警告：无'
                ];
                setToolResult('clip_result', lines.join('\n'));
            } catch (e) {
                buildClipTunePlan();
                setToolResult('clip_result', `${document.getElementById('clip_result')?.textContent || ''}\n\n处理失败，当前先保留为建议模式：${e.message || e}`);
            }
        }

        function buildExportPlan() {
            const exportDir = document.getElementById('export_dir')?.value?.trim();
            const pattern = document.getElementById('export_pattern')?.value?.trim() || '{draft}_{index}';
            const format = document.getElementById('export_format')?.value || 'mp4';
            const resolution = document.getElementById('export_resolution')?.value || '1080p';
            const fps = parseInt(document.getElementById('export_fps')?.value || '30', 10);
            const exportEnabled = !!document.getElementById('export_enable')?.checked;
            const withCover = !!document.getElementById('export_cover')?.checked;
            const withLog = !!document.getElementById('export_log')?.checked;
            const batchCount = parseInt(document.getElementById('batch_count')?.value || '1', 10);
            const draftName = currentDraftPath ? currentDraftPath.split(/[\\/]/).filter(Boolean).pop() : 'draft';
            const samples = [];
            for (let i = 1; i <= Math.min(batchCount, 5); i += 1) {
                samples.push(pattern.replace('{draft}', draftName).replace('{index}', String(i).padStart(2, '0')) + `.${format}`);
            }
            const lines = [
                `导出目录：${exportDir || '尚未填写，建议先设置固定输出目录'}`,
                `命名模板：${pattern}`,
                `样例文件：${samples.join(' / ')}`,
                `导出执行：${exportEnabled ? '生成后自动导出' : '仅生成草稿，不直接导出'}`,
                `格式设置：${format.toUpperCase()} / ${resolution} / ${fps} FPS`,
                `附加动作：${withCover ? '生成封面' : '不生成封面'}，${withLog ? '保留导出清单' : '不保留导出清单'}`,
                `执行建议：先导出 1 条做抽检，再批量导出剩余 ${batchCount} 条。`
            ];
            setToolResult('export_result', lines.join('\n'));
        }

        function renderExportDraftQueue() {
            const summary = document.getElementById('export_queue_summary');
            const list = document.getElementById('export_queue_list');
            if (!summary || !list) return;
            if (!exportDraftQueue.length) {
                summary.textContent = '当前还没有待导出的草稿。';
                list.textContent = '待导出草稿会显示在这里。';
                return;
            }
            summary.textContent = `已加入 ${exportDraftQueue.length} 个待导出草稿。`;
            list.innerHTML = exportDraftQueue.map((item, index) => `
                <div class="key-item">
                    <div class="key-row"><strong>${item.name || '未命名草稿'}</strong><span class="key-badge">${item.source || '本机草稿'}</span></div>
                    <div class="hint">${item.path}</div>
                    <div class="key-actions"><button class="effect-add" type="button" onclick="removeExportDraftAt(${index})">移除</button></div>
                </div>
            `).join('');
        }

        function removeExportDraftAt(index) {
            exportDraftQueue.splice(index, 1);
            renderExportDraftQueue();
        }

        function addCurrentDraftToExportQueue() {
            const draftPath = getDraftElement('path')?.value?.trim() || currentDraftPath || '';
            if (!draftPath) {
                setToolResult('export_result', '请先选择当前草稿，再加入待导出列表。');
                return;
            }
            const exists = exportDraftQueue.some((item) => item.path === draftPath);
            if (!exists) {
                exportDraftQueue.push({
                    path: draftPath,
                    name: draftPath.split(/[\\/]/).filter(Boolean).pop() || draftPath,
                    source: currentDraftVersion === 'capcut' ? 'CapCut 国际版' : '剪映'
                });
            }
            renderExportDraftQueue();
                setToolResult('export_result', '当前草稿已加入待导出列表。');
        }

        function addDiscoveredDraftsToExportQueue() {
            const drafts = Array.isArray(window.__vfDiscoveredDrafts) ? window.__vfDiscoveredDrafts : [];
            if (!drafts.length) {
                setToolResult('export_result', '当前没有最近发现草稿，请先刷新草稿列表。');
                return;
            }
            drafts.forEach((item) => {
                if (!item?.path) return;
                if (exportDraftQueue.some((entry) => entry.path === item.path)) return;
                exportDraftQueue.push({
                    path: item.path,
                    name: item.name || (item.path.split(/[\\/]/).filter(Boolean).pop() || item.path),
                    source: item.source || '本机草稿'
                });
            });
            renderExportDraftQueue();
            setToolResult('export_result', `已加入最近发现的 ${drafts.length} 个草稿。`);
        }

        function clearExportDraftQueue() {
            exportDraftQueue = [];
            renderExportDraftQueue();
            setToolResult('export_result', '已清空待导出草稿列表。');
        }

        function renderSplitDraftQueue() {
            const summary = document.getElementById('split_queue_summary');
            const list = document.getElementById('split_queue_list');
            if (!summary || !list) return;
            if (!splitDraftQueue.length) {
                summary.textContent = '当前还没有加入要查看的草稿。';
                list.textContent = '加入后的草稿会显示在这里。';
                return;
            }
            summary.textContent = `已加入 ${splitDraftQueue.length} 个草稿。`;
            list.innerHTML = splitDraftQueue.map((item, index) => `
                <div class="key-item">
                    <div class="key-row"><strong>${item.name || '未命名草稿'}</strong><span class="key-badge">${item.source || '本机草稿'}</span></div>
                    <div class="hint">${item.path}</div>
                    <div class="key-actions"><button class="effect-add" type="button" onclick="removeSplitDraftAt(${index})">移除</button></div>
                </div>
            `).join('');
        }

        function removeSplitDraftAt(index) {
            splitDraftQueue.splice(index, 1);
            renderSplitDraftQueue();
        }

        function addDiscoveredDraftsToSplitQueue() {
            const drafts = Array.isArray(window.__vfDiscoveredDrafts) ? window.__vfDiscoveredDrafts : [];
            if (!drafts.length) {
                setToolResult('split_multi_result', '当前没有最近发现草稿，请先刷新草稿列表。');
                return;
            }
            drafts.forEach((item) => {
                if (!item?.path) return;
                if (splitDraftQueue.some((entry) => entry.path === item.path)) return;
                splitDraftQueue.push({
                    path: item.path,
                    name: item.name || (item.path.split(/[\\/]/).filter(Boolean).pop() || item.path),
                    source: item.source || '本机草稿'
                });
            });
            renderSplitDraftQueue();
            setToolResult('split_multi_result', `已加入最近发现的 ${drafts.length} 个草稿。`);
        }

        function clearSplitDraftQueue() {
            splitDraftQueue = [];
            renderSplitDraftQueue();
            setToolResult('split_multi_result', '已清空待查看草稿列表。');
        }

        function runAlignTool() {
            const pointsRaw = document.getElementById('align_points')?.value?.trim();
            const offset = parseFloat(document.getElementById('align_offset')?.value || '0');
            const scale = parseFloat(document.getElementById('align_scale')?.value || '1');
            if (!pointsRaw) {
                setToolResult('align_result', '请先填写时间点。');
                return;
            }
            const points = pointsRaw.split(/[,，\s]+/).map(v => parseFloat(v)).filter(v => !isNaN(v));
            if (!points.length) {
                setToolResult('align_result', '未识别到有效时间点。');
                return;
            }
            const result = points.map(v => Math.max(0, ((v * scale) + offset))).map(v => v.toFixed(2));
            const lines = [
                `原始时间点：${points.map(v => v.toFixed(2)).join(', ')}`,
                `偏移：${offset}s / 缩放：${scale}`,
                `对齐结果：${result.join(', ')}`,
                '使用建议：先复制到字幕或标记文件，再做一次人工抽检。'
            ];
            setToolResult('align_result', lines.join('\n'));
        }

        function listMap() {
            return {
                video_effect_list: effectsState.video_effects,
                video_anim_list: effectsState.video_animations,
                transition_list: effectsState.transitions,
                mask_list: effectsState.masks,
                bg_list: effectsState.backgrounds,
                vf_list: effectsState.video_keyframes,
                text_anim_list: effectsState.text_animations,
                text_bubble_list: effectsState.text_bubbles,
                text_effect_list: effectsState.text_effects,
                audio_effect_list: effectsState.audio_effects,
                audio_fade_list: effectsState.audio_fades,
                audio_kf_list: effectsState.audio_keyframes,
                duo_text_list: duoState.text_templates,
                duo_video_effect_list: duoState.video_effects,
                duo_transition_list: duoState.transitions,
                duo_face_list: duoState.face_effects,
                duo_sticker_list: duoState.stickers
            };
        }

        function getEffectDom() {
            return {
                videoEffectList: document.getElementById('video_effect_list'),
                videoAnimList: document.getElementById('video_anim_list'),
                transitionList: document.getElementById('transition_list'),
                maskList: document.getElementById('mask_list'),
                bgList: document.getElementById('bg_list'),
                videoKeyframeList: document.getElementById('vf_list'),
                textAnimList: document.getElementById('text_anim_list'),
                textBubbleList: document.getElementById('text_bubble_list'),
                textEffectList: document.getElementById('text_effect_list'),
                audioEffectList: document.getElementById('audio_effect_list'),
                audioFadeList: document.getElementById('audio_fade_list'),
                audioKeyframeList: document.getElementById('audio_kf_list'),
                duoTextList: document.getElementById('duo_text_list'),
                duoVideoEffectList: document.getElementById('duo_video_effect_list'),
                duoTransitionList: document.getElementById('duo_transition_list'),
                duoFaceList: document.getElementById('duo_face_list'),
                duoStickerList: document.getElementById('duo_sticker_list'),
                presetSelect: document.getElementById('preset_select'),
                videoFilter: document.getElementById('video_filter'),
                videoFilterIntensity: document.getElementById('video_filter_intensity'),
                videoFilterIntensitySlider: document.getElementById('video_filter_intensity_slider'),
                duoTrackSelect: document.getElementById('duo_track_select'),
                duoTrackInfo: document.getElementById('duo_track_info')
            };
        }

        function initEffectInputs() {
            document.querySelectorAll('input[type="range"]').forEach((input) => {
                if (input.dataset.rangeBound === 'true') return;
                input.dataset.rangeBound = 'true';
                let valueNode = input.nextElementSibling;
                if (!valueNode || !valueNode.classList?.contains('range-value')) {
                    valueNode = document.createElement('span');
                    valueNode.className = 'range-value';
                    input.insertAdjacentElement('afterend', valueNode);
                }
                const syncValue = () => {
                    valueNode.textContent = input.value || '';
                };
                syncValue();
                input.addEventListener('input', syncValue);
                input.addEventListener('change', syncValue);
            });
        }

        function getEffectItems(listId) {
            return listMap()[listId];
        }

        function getEffectListElement(listId) {
            return document.getElementById(listId);
        }

        function effectRenderConfigs() {
            return [
                {domKey: 'videoEffectList', listId: 'video_effect_list', items: effectsState.video_effects, format: item => `视频特效: ${item.type}`},
                {domKey: 'videoAnimList', listId: 'video_anim_list', items: effectsState.video_animations, format: item => `视频动画: ${item.type} / ${item.name}`},
                {domKey: 'transitionList', listId: 'transition_list', items: effectsState.transitions, format: item => `转场: ${item.type}`},
                {domKey: 'maskList', listId: 'mask_list', items: effectsState.masks, format: item => `蒙版: ${item.type}`},
                {domKey: 'bgList', listId: 'bg_list', items: effectsState.backgrounds, format: item => `背景: ${item.type}`},
                {domKey: 'videoKeyframeList', listId: 'vf_list', items: effectsState.video_keyframes, format: item => `关键帧: ${item.property} @ ${item.time}s`},
                {domKey: 'textAnimList', listId: 'text_anim_list', items: effectsState.text_animations, format: item => `文字动画: ${item.type} / ${item.name}`},
                {domKey: 'textBubbleList', listId: 'text_bubble_list', items: effectsState.text_bubbles, format: item => `气泡: ${item.effect_id}`},
                {domKey: 'textEffectList', listId: 'text_effect_list', items: effectsState.text_effects, format: item => `花字: ${item.effect_id}`},
                {domKey: 'audioEffectList', listId: 'audio_effect_list', items: effectsState.audio_effects, format: item => `音频特效: ${item.name}`},
                {domKey: 'audioFadeList', listId: 'audio_fade_list', items: effectsState.audio_fades, format: item => `淡入淡出: ${item.in}s / ${item.out}s`},
                {domKey: 'audioKeyframeList', listId: 'audio_kf_list', items: effectsState.audio_keyframes, format: item => `音频关键帧: ${item.time}s / ${item.volume}`},
                {domKey: 'duoTextList', listId: 'duo_text_list', items: duoState.text_templates, format: item => `文字模板: ${item.name || item.id || ''}`},
                {domKey: 'duoVideoEffectList', listId: 'duo_video_effect_list', items: duoState.video_effects, format: item => `画面特效: ${item.name || item.id || ''}`},
                {domKey: 'duoTransitionList', listId: 'duo_transition_list', items: duoState.transitions, format: item => `转场: ${item.name || item.id || ''}`},
                {domKey: 'duoFaceList', listId: 'duo_face_list', items: duoState.face_effects, format: item => `脸部特效: ${item.name || item.id || ''}`},
                {domKey: 'duoStickerList', listId: 'duo_sticker_list', items: duoState.stickers, format: item => `贴纸: ${item.name || item.id || ''}`}
            ];
        }

        function renderEffectList(listId, items, formatter) {
            const el = getEffectListElement(listId);
            if (!el) return;
            if (!items.length) {
                el.innerHTML = '<div class="hint">暂无配置</div>';
                return;
            }
            el.innerHTML = items.map((item, idx) => {
                const text = formatter ? formatter(item) : JSON.stringify(item);
                return `<div class="effect-item"><span>${text}</span>`
                    + `<button class="effect-remove" type="button" onclick="editEffectItem('${listId}', ${idx})">编辑</button>`
                    + `<button class="effect-remove" type="button" onclick="cloneEffectItem('${listId}', ${idx})">克隆</button>`
                    + `<button class="effect-remove" type="button" onclick="removeEffectItem('${listId}', ${idx})">移除</button>`
                    + `</div>`;
            }).join('');
        }

        function removeEffectItem(listId, idx) {
            const list = getEffectItems(listId);
            if (!list) return;
            list.splice(idx, 1);
            renderAllEffectLists();
        }

        function cloneEffectItem(listId, idx) {
            const list = getEffectItems(listId);
            if (!list) return;
            list.splice(idx + 1, 0, JSON.parse(JSON.stringify(list[idx])));
            renderAllEffectLists();
        }

        function editEffectItem(listId, idx) {
            const list = getEffectItems(listId);
            if (!list) return;
            const raw = prompt('编辑这项设置（请保持原有格式）', JSON.stringify(list[idx], null, 2));
            if (!raw) return;
            try {
                list[idx] = JSON.parse(raw);
                renderAllEffectLists();
            } catch (e) {
                notify('填写格式不正确，未保存这次修改。', 'warn');
            }
        }

        function renderAllEffectLists() {
            const effectDom = getEffectDom();
            effectRenderConfigs().forEach((config) => {
                if (!effectDom[config.domKey]) return;
                renderEffectList(config.listId, config.items, config.format);
            });
        }

        function applyPreset() {
            const effectDom = getEffectDom();
            const presetKey = effectDom.presetSelect?.value || '';
            const preset = presetMap[presetKey];
            if (!preset) return;
            effectsState.video_effects = (preset.video?.effects || []).slice();
            effectsState.video_animations = (preset.video?.animations || []).slice();
            effectsState.transitions = (preset.video?.transitions || []).slice();
            effectsState.text_animations = (preset.text?.animations || []).slice();
            const filter = preset.video?.filters?.[0];
            if (filter) {
                if (effectDom.videoFilter) effectDom.videoFilter.value = filter.type;
                if (effectDom.videoFilterIntensity) effectDom.videoFilterIntensity.value = filter.intensity;
                if (effectDom.videoFilterIntensitySlider) effectDom.videoFilterIntensitySlider.value = filter.intensity;
            }
            renderAllEffectLists();
        }
        function updateDuoTrackOptions(tracks = [], segmentCounts = {}) {
            const effectDom = getEffectDom();
            const sel = effectDom.duoTrackSelect;
            if (!sel) return;
            const options = ['<option value="">全部</option>'];
            tracks.forEach(t => {
                const count = segmentCounts[t.name] || 0;
                options.push(`<option value="${t.name}" data-count="${count}">${t.name} (${t.type}, ${count}段)</option>`);
            });
            sel.innerHTML = options.join('');
            sel.onchange = () => {
                const opt = sel.options[sel.selectedIndex];
                const c = parseInt(opt.getAttribute('data-count') || '0', 10);
                const info = effectDom.duoTrackInfo;
                if (info) info.innerText = opt.value ? (c > 0 ? `可用片段范围：0 ~ ${c - 1}` : '当前位置没有片段') : '';
            };
        }

        function getDraftDom(panel = null) {
            return {
                draftPath: getDraftElement('path', panel),
                draftStatus: getDraftElement('status', panel),
                materialsArea: document.getElementById('materials_area'),
                materialsList: document.getElementById('materials_list'),
                textsArea: document.getElementById('texts_area'),
                folderSection: document.getElementById('folder_section'),
                optionsSection: document.getElementById('options_section'),
                effectsSection: document.getElementById('effects_section')
            };
        }

        function resetDraftInfo(message = '') {
            currentDraftPath = '';
            currentDraftVersion = getDraftElement('version')?.value || 'all';
            materialsConfig = [];
            textsConfig = [];
            draftTrackMeta = [];
            const dom = getDraftDom();
            if (dom.materialsArea) dom.materialsArea.style.display = 'none';
            if (dom.materialsList) dom.materialsList.innerHTML = '';
            if (dom.textsArea) {
                dom.textsArea.innerHTML = '';
                dom.textsArea.style.display = 'none';
            }
            if (dom.folderSection) dom.folderSection.style.display = 'none';
            if (dom.optionsSection) {
                dom.optionsSection.style.display = 'none';
                dom.optionsSection.open = false;
            }
            if (dom.effectsSection) {
                dom.effectsSection.dataset.ready = 'false';
            }
            if (dom.draftStatus) dom.draftStatus.textContent = message || '';
            syncDraftShellValues(message);
            updateDuoTrackOptions([], {});
            syncEffectsSectionVisibility();
            updateWorkspaceDraftBadge();
            updatePrimaryActionState();
            updateMixModeUI();
        }

        async function loadDraftInfo() {
            const dom = getDraftDom();
            const draftPath = dom.draftPath?.value?.trim();
            if (!draftPath) {
                resetDraftInfo('请先选择草稿');
                return;
            }
            if (!getToken()) {
                setAuthMessage('请先登录后选择草稿');
                toggleProtectedUI(false);
                return;
            }
            if (dom.draftStatus) dom.draftStatus.textContent = '正在整理当前草稿内容...';

            try {
                const res = await authFetch('/api/draft/inspect', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({draft_path: draftPath})
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '草稿读取失败');
                }

                currentDraftPath = draftPath;
                currentDraftVersion = getDraftElement('version')?.value || inferDraftVersion(draftPath);
                materialsConfig = data.materials || [];
                textsConfig = data.texts || [];
                draftTrackMeta = data.tracks || [];
                updateDuoTrackOptions(data.tracks || [], data.segment_counts || {});
                setWorkspaceSettings({
                    last_draft_path: draftPath,
                    last_draft_version: currentDraftVersion
                });

                if (materialsConfig.length > 0) {
                    if (dom.materialsList) {
                        dom.materialsList.innerHTML = renderCompactMaterials(materialsConfig);
                    }
                    if (dom.materialsArea) dom.materialsArea.style.display = 'block';
                } else {
                    if (dom.materialsArea) dom.materialsArea.style.display = 'none';
                }

                if (textsConfig.length > 0) {
                    if (dom.textsArea) {
                        dom.textsArea.innerHTML = renderCompactTexts(textsConfig);
                        dom.textsArea.style.display = 'block';
                    }
                } else {
                    if (dom.textsArea) dom.textsArea.style.display = 'none';
                }

                if (materialsConfig.length > 0 || textsConfig.length > 0) {
                    if (dom.folderSection) dom.folderSection.style.display = 'block';
                    if (dom.optionsSection) {
                        dom.optionsSection.style.display = 'block';
                        dom.optionsSection.open = true;
                    }
                    if (dom.effectsSection) dom.effectsSection.dataset.ready = 'true';
                    syncEffectsSectionVisibility();
                    renderAllEffectLists();
                } else {
                    if (dom.folderSection) dom.folderSection.style.display = 'none';
                    if (dom.optionsSection) {
                        dom.optionsSection.style.display = 'none';
                        dom.optionsSection.open = false;
                    }
                    if (dom.effectsSection) {
                        dom.effectsSection.dataset.ready = 'false';
                    }
                    syncEffectsSectionVisibility();
                }

                if (dom.draftStatus) {
                    const matCount = materialsConfig.length;
                    const textCount = textsConfig.length;
                    dom.draftStatus.textContent = `草稿已就绪：素材 ${matCount} 个，文字 ${textCount} 段`;
                }
                syncDraftShellValues(dom.draftStatus?.textContent || '');
                updateWorkspaceDraftBadge();
                toggleProtectedUI(!!getToken());
                updatePrimaryActionState();
                updateMixModeUI();
            } catch (error) {
                resetDraftInfo(`草稿读取失败：${error.message}`);
            }
        }

        async function selectFolder() {
            const response = await fetch('/api/browse-folder', {method: 'POST'});
            const data = await response.json();
            document.getElementById('folder_path').value = data.folder || '';
            if (data.folder) {
                pushRecentMaterialFolder(data.folder);
                setWorkspaceSettings({last_materials_root: data.folder});
            }
            updatePrimaryActionState();
        }

        async function selectAudioFolder() {
            const response = await fetch('/api/browse-folder', {method: 'POST'});
            const data = await response.json();
            const input = document.getElementById('audio_folder_path');
            if (input) input.value = data.folder || '';
            if (data.folder) {
                setWorkspaceSettings({last_audio_root: data.folder});
            }
        }

        async function selectDraftFolder() {
            const response = await fetch('/api/browse-folder', {method: 'POST'});
            const data = await response.json();
            const input = getDraftElement('path');
            if (input) input.value = data.folder || '';
            if (data.folder) {
                await loadDraftInfo();
            } else {
                updatePrimaryActionState();
            }
        }

        function buildEffectsConfig() {
            const cfg = {
                video: {filters: [], effects: [], animations: [], transitions: [], masks: [], keyframes: [], background: []},
                text: {animations: [], bubbles: [], effects: []},
                audio: {effects: [], fades: [], keyframes: []}
            };

            const filter = document.getElementById('video_filter').value;
            const intensity = parseInt(document.getElementById('video_filter_intensity').value || '0', 10);
            if (filter) cfg.video.filters.push({type: filter, intensity});

            const transition = document.getElementById('transition_type').value;
            if (transition) {
                const duration = parseFloat(document.getElementById('transition_duration').value || '');
                const indexes = parseIndexes(document.getElementById('transition_indexes').value);
                const item = {type: transition};
                if (!isNaN(duration)) item.duration = duration;
                if (indexes) item.indexes = indexes;
                cfg.video.transitions.push(item);
            }

            const textIntro = document.getElementById('text_intro').value;
            if (textIntro) cfg.text.animations.push({type: 'TextIntro', name: textIntro});

            const audioEffectType = document.getElementById('audio_effect_type').value;
            const audioEffectName = document.getElementById('audio_effect_custom').value.trim() || document.getElementById('audio_effect').value;
            if (audioEffectName) {
                const params = parseMaybeJson(document.getElementById('audio_effect_params').value.trim());
                const indexes = parseIndexes(document.getElementById('audio_effect_indexes').value);
                const item = {type: audioEffectType || 'AudioSceneEffectType', name: audioEffectName};
                if (params) item.params = params;
                if (indexes) item.indexes = indexes;
                cfg.audio.effects.push(item);
            }

            if (effectsState.video_effects.length) cfg.video.effects.push(...effectsState.video_effects);
            if (effectsState.video_animations.length) cfg.video.animations.push(...effectsState.video_animations);
            if (effectsState.transitions.length) cfg.video.transitions.push(...effectsState.transitions);
            if (effectsState.masks.length) cfg.video.masks.push(...effectsState.masks);
            if (effectsState.backgrounds.length) cfg.video.background.push(...effectsState.backgrounds);
            if (effectsState.video_keyframes.length) cfg.video.keyframes.push(...effectsState.video_keyframes);
            if (effectsState.text_animations.length) cfg.text.animations.push(...effectsState.text_animations);
            if (effectsState.text_bubbles.length) cfg.text.bubbles.push(...effectsState.text_bubbles);
            if (effectsState.text_effects.length) cfg.text.effects.push(...effectsState.text_effects);
            if (effectsState.audio_effects.length) cfg.audio.effects.push(...effectsState.audio_effects);
            if (effectsState.audio_fades.length) cfg.audio.fades.push(...effectsState.audio_fades);
            if (effectsState.audio_keyframes.length) cfg.audio.keyframes.push(...effectsState.audio_keyframes);

            const raw = document.getElementById('effects_json')?.value?.trim();
            if (raw) {
                try { return JSON.parse(raw); } catch (e) { notify('高级效果设置格式不正确，已先按基础设置继续。', 'warn'); }
            }
            return cfg;
        }
        function addVideoEffect() {
            const videoEffectType = document.getElementById('video_effect_type').value.trim();
            if (!videoEffectType) return;
            const params = parseMaybeJson(document.getElementById('video_effect_params').value.trim());
            const indexes = parseIndexes(document.getElementById('video_effect_indexes').value);
            const item = {type: videoEffectType};
            if (params) item.params = params;
            if (indexes) item.indexes = indexes;
            effectsState.video_effects.push(item);
            renderAllEffectLists();
        }

        function addVideoAnimation() {
            const videoAnimType = document.getElementById('video_anim_type').value;
            const videoAnimName = document.getElementById('video_anim_name').value.trim();
            if (!videoAnimType || !videoAnimName) return;
            const duration = parseFloat(document.getElementById('video_anim_duration').value || '');
            const indexes = parseIndexes(document.getElementById('video_anim_indexes').value);
            const item = {type: videoAnimType, name: videoAnimName};
            if (!isNaN(duration)) item.duration = duration;
            if (indexes) item.indexes = indexes;
            effectsState.video_animations.push(item);
            renderAllEffectLists();
        }

        function addTransition() {
            const transition = document.getElementById('transition_type').value;
            if (!transition) return;
            const duration = parseFloat(document.getElementById('transition_duration').value || '');
            const indexes = parseIndexes(document.getElementById('transition_indexes').value);
            const item = {type: transition};
            if (!isNaN(duration)) item.duration = duration;
            if (indexes) item.indexes = indexes;
            effectsState.transitions.push(item);
            renderAllEffectLists();
        }

        function addMask() {
            const maskType = document.getElementById('mask_type').value.trim();
            if (!maskType) return;
            const centerRaw = document.getElementById('mask_center').value.trim();
            let centerX = 0.0;
            let centerY = 0.0;
            if (centerRaw.includes(',')) {
                const parts = centerRaw.split(',');
                centerX = parseFloat(parts[0].trim()) || 0.0;
                centerY = parseFloat(parts[1].trim()) || 0.0;
            }
            const size = parseFloat(document.getElementById('mask_size').value || '');
            const rotation = parseFloat(document.getElementById('mask_rotation').value || '');
            const feather = parseFloat(document.getElementById('mask_feather').value || '');
            const invert = document.getElementById('mask_invert').value === 'true';
            const rectWidth = parseFloat(document.getElementById('mask_rect_width').value || '');
            const roundCorner = parseFloat(document.getElementById('mask_round_corner').value || '');
            const indexes = parseIndexes(document.getElementById('mask_indexes').value);
            const item = {type: maskType, center_x: centerX, center_y: centerY};
            if (!isNaN(size)) item.size = size;
            if (!isNaN(rotation)) item.rotation = rotation;
            if (!isNaN(feather)) item.feather = feather;
            if (invert) item.invert = true;
            if (!isNaN(rectWidth)) item.rect_width = rectWidth;
            if (!isNaN(roundCorner)) item.round_corner = roundCorner;
            if (indexes) item.indexes = indexes;
            effectsState.masks.push(item);
            renderAllEffectLists();
        }

        function addBackground() {
            const bgType = document.getElementById('bg_type').value.trim();
            if (!bgType) return;
            const blur = parseFloat(document.getElementById('bg_blur').value || '');
            const color = document.getElementById('bg_color').value.trim();
            const indexes = parseIndexes(document.getElementById('bg_indexes').value);
            const item = {type: bgType};
            if (!isNaN(blur)) item.blur = blur;
            if (color) item.color = color;
            if (indexes) item.indexes = indexes;
            effectsState.backgrounds.push(item);
            renderAllEffectLists();
        }

        function addVideoKeyframe() {
            const vfProp = document.getElementById('vf_prop').value.trim();
            const vfTime = parseFloat(document.getElementById('vf_time').value || '');
            const vfValueRaw = document.getElementById('vf_value').value.trim();
            if (!vfProp || isNaN(vfTime) || !vfValueRaw) return;
            const value = parseMaybeJson(vfValueRaw) ?? vfValueRaw;
            const indexes = parseIndexes(document.getElementById('vf_indexes').value);
            const item = {property: vfProp, time: vfTime, value: value};
            if (indexes) item.indexes = indexes;
            effectsState.video_keyframes.push(item);
            renderAllEffectLists();
        }

        function addTextAnimation() {
            const textAnimType = document.getElementById('text_anim_type').value;
            const textAnimName = document.getElementById('text_anim_name').value.trim();
            if (!textAnimType || !textAnimName) return;
            const duration = parseFloat(document.getElementById('text_anim_duration').value || '');
            const indexes = parseIndexes(document.getElementById('text_anim_indexes').value);
            const item = {type: textAnimType, name: textAnimName};
            if (!isNaN(duration)) item.duration = duration;
            if (indexes) item.indexes = indexes;
            effectsState.text_animations.push(item);
            renderAllEffectLists();
        }

        function addTextBubble() {
            const bubbleEffectId = document.getElementById('text_bubble_effect_id').value.trim();
            const bubbleResId = document.getElementById('text_bubble_resource_id').value.trim();
            if (!bubbleEffectId || !bubbleResId) return;
            const indexes = parseIndexes(document.getElementById('text_bubble_indexes').value);
            const item = {effect_id: bubbleEffectId, resource_id: bubbleResId};
            if (indexes) item.indexes = indexes;
            effectsState.text_bubbles.push(item);
            renderAllEffectLists();
        }

        function addTextEffect() {
            const textEffectId = document.getElementById('text_effect_id').value.trim();
            if (!textEffectId) return;
            const indexes = parseIndexes(document.getElementById('text_effect_indexes').value);
            const item = {effect_id: textEffectId};
            if (indexes) item.indexes = indexes;
            effectsState.text_effects.push(item);
            renderAllEffectLists();
        }

        function addAudioEffect() {
            const audioEffectType = document.getElementById('audio_effect_type').value;
            const audioEffectName = document.getElementById('audio_effect_custom').value.trim() || document.getElementById('audio_effect').value;
            if (!audioEffectName) return;
            const params = parseMaybeJson(document.getElementById('audio_effect_params').value.trim());
            const indexes = parseIndexes(document.getElementById('audio_effect_indexes').value);
            const item = {type: audioEffectType || 'AudioSceneEffectType', name: audioEffectName};
            if (params) item.params = params;
            if (indexes) item.indexes = indexes;
            effectsState.audio_effects.push(item);
            renderAllEffectLists();
        }

        function addAudioFade() {
            const audioFadeIn = parseFloat(document.getElementById('audio_fade_in').value || '');
            const audioFadeOut = parseFloat(document.getElementById('audio_fade_out').value || '');
            if (isNaN(audioFadeIn) || isNaN(audioFadeOut)) return;
            const indexes = parseIndexes(document.getElementById('audio_fade_indexes').value);
            const item = {in: audioFadeIn, out: audioFadeOut};
            if (indexes) item.indexes = indexes;
            effectsState.audio_fades.push(item);
            renderAllEffectLists();
        }

        function addAudioKeyframe() {
            const audioKfTime = parseFloat(document.getElementById('audio_kf_time').value || '');
            const audioKfVolume = parseFloat(document.getElementById('audio_kf_volume').value || '');
            if (isNaN(audioKfTime) || isNaN(audioKfVolume)) return;
            const indexes = parseIndexes(document.getElementById('audio_kf_indexes').value);
            const item = {time: audioKfTime, volume: audioKfVolume};
            if (indexes) item.indexes = indexes;
            effectsState.audio_keyframes.push(item);
            renderAllEffectLists();
        }

        async function submitBatch() {
            if (!getToken()) {
                setAuthMessage('请先登录后再生成');
                toggleProtectedUI(false);
                return;
            }
            const draftPath = getDraftElement('path')?.value?.trim();
            if (!draftPath) {
                notify('请先选择草稿。', 'warn');
                return;
            }
            if (!currentDraftPath || currentDraftPath !== draftPath) {
                notify('当前草稿状态已变化，请重新选择后再试。', 'warn');
                return;
            }
            const folderPath = document.getElementById('folder_path').value;
            if (!folderPath) {
                notify('请先选择素材目录。', 'warn');
                return;
            }
            const batchCount = parseInt(document.getElementById('batch_count').value) || 1;
            if (batchCount < 1 || batchCount > 100) {
                notify('批量生成数量需要在 1 到 100 之间。', 'warn');
                return;
            }

            const textsInput = [];
            for (let i = 0; i < textsConfig.length; i++) {
                const input = document.getElementById(`text_${i}`);
                if (input) textsInput.push({ index: i, contents: [input.value], rule: 'order' });
            }

            const replaceMaterials = document.getElementById('replace_materials').checked;
            const replaceTexts = document.getElementById('replace_texts').checked;
            const replaceAudios = document.getElementById('replace_audios')?.checked || false;
            if (!replaceMaterials && !replaceTexts && !replaceAudios) {
                notify('请至少选择一种替换内容。', 'warn');
                return;
            }
            const replaceType = document.getElementById('replace_type')?.value || 'both';
            const replaceMode = document.getElementById('replace_mode')?.value || 'order';
            const replaceStrategy = getSelectedReplaceStrategy();
            const audioEnabled = !!document.getElementById('audio_enabled')?.checked;
            const audioFolderPath = document.getElementById('audio_folder_path')?.value?.trim();
            const exportEnabled = !!document.getElementById('export_enable')?.checked;
            const exportPath = document.getElementById('export_dir')?.value?.trim();
            const exportFormat = document.getElementById('export_format')?.value || 'mp4';
            const exportResolution = document.getElementById('export_resolution')?.value || '1080p';
            const exportFps = parseInt(document.getElementById('export_fps')?.value || '30', 10);

            const payload = {
                draft_path: draftPath,
                materials_root: folderPath,
                texts_input: textsInput,
                batch_count: batchCount,
                replace_materials: replaceMaterials,
                replace_texts: replaceTexts,
                replace_audios: replaceAudios,
                replace_type: replaceType,
                replace_mode: replaceMode,
                replace_strategy: replaceStrategy,
                audio_enabled: audioEnabled,
                audio_root: audioFolderPath || null,
                export_enabled: exportEnabled,
                export_path: exportPath || null,
                export_format: exportFormat,
                export_resolution: exportResolution,
                export_fps: exportFps,
                effects_config: buildEffectsConfig(),
                duo_config: buildDuoConfig()
            };

            document.getElementById('submitBtn').disabled = true;
            document.getElementById('progress-area').style.display = 'block';
            document.getElementById('progress-fill').style.width = '0%';
            document.getElementById('progress-text').innerText = '提交任务中...';

            try {
                const response = await authFetch('/api/generate-batch', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(payload)
                });
                const result = await response.json();
                if (result.job_id) {
                    document.getElementById('progress-text').innerText = `任务已提交，编号 ${result.job_id}，正在处理...`;
                    pollTaskStatus(result.job_id);
                } else {
                    throw new Error(result.error || '未知错误');
                }
            } catch (error) {
                document.getElementById('progress-text').innerText = `提交失败：${error.message}`;
                notify(error.message || '提交失败，请检查当前设置。', 'warn');
                document.getElementById('submitBtn').disabled = false;
            }
        }
        async function loadResourceTypes() {
            try {
                const res = await fetch('/api/effects/types');
                const data = await res.json();
                const sel = document.getElementById('effect_type');
                if (sel && data.types) {
                    sel.innerHTML = data.types.map(t => `<option value="${t}">${t}</option>`).join('');
                }
            } catch (e) {}
        }

        async function searchResources() {
            const effectType = document.getElementById('effect_type').value;
            const keyword = document.getElementById('effect_keyword')?.value?.trim();
            const limit = parseInt(document.getElementById('effect_limit')?.value || '50', 10);
            const isVip = document.getElementById('effect_is_vip')?.checked || false;
            if (!effectType) {
                notify('请先选择资源类型。', 'warn');
                return;
            }
            const res = await fetch('/api/effects/list', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({effect_type: effectType, keyword, limit, is_vip: isVip})
            });
            const data = await res.json();
            resourceCache = data.effects || [];
            renderResourceResults(resourceCache);
        }

        function renderResourceResults(items) {
            const results = document.getElementById('resource_results');
            if (!results) return;
            if (!items.length) {
                results.innerHTML = '<div class="hint">无匹配资源</div>';
                return;
            }
            results.innerHTML = items.map((item, idx) => {
                const resourceId = item.effect_id || item.resource_id || item.id || '';
                return `<div class="resource-row">名称: ${item.name || ''} | id: ${resourceId} <button class="effect-add" type="button" onclick="useResource(${idx})">加入当前效果</button></div>`;
            }).join('');
        }

        function useResource(idx) {
            const item = resourceCache[idx];
            if (!item) return;
            const selectedType = document.getElementById('effect_type')?.value || '';
            const effectId = item.effect_id || item.id || '';
            const resourceId = item.resource_id || item.id || '';
            const effectName = item.name || effectId || resourceId;

            if (selectedType === 'TransitionType') {
                effectsState.transitions.push({type: effectName});
            } else if (selectedType === 'filter_type') {
                const filterInput = document.getElementById('video_filter');
                if (filterInput) filterInput.value = effectName;
            } else if (selectedType === 'AudioSceneEffectType') {
                effectsState.audio_effects.push({type: 'AudioSceneEffectType', name: effectName});
            } else if (selectedType === 'TextIntro' || selectedType === 'TextOutro' || selectedType === 'TextLoopAnim') {
                effectsState.text_animations.push({type: selectedType, name: effectName});
            } else {
                effectsState.video_effects.push({type: effectName});
            }

            renderAllEffectLists();
        }

        async function loadDuoCategories() {
            try {
                const res = await fetch('/api/duo/resources/categories');
                const data = await res.json();
                const sel = document.getElementById('duo_category');
                if (sel && data.categories) {
                    sel.innerHTML = data.categories.map(c => `<option value="${c}">${c}</option>`).join('');
                }
            } catch (e) {}
        }

        function renderDuoLists() {
            renderAllEffectLists();
        }

        function toggleDuoFields() {
            // 简化：保持字段可见
        }

        async function searchDuoResources() {
            const category = document.getElementById('duo_category').value;
            const keyword = document.getElementById('duo_keyword').value.trim();
            const limit = parseInt(document.getElementById('duo_limit').value || '50', 10);
            const page = parseInt(document.getElementById('duo_page')?.value || '1', 10);
            const offset = (page - 1) * limit;
            const pager = document.getElementById('duo_pager_info');
            if (!category) {
                notify('请先选择资源分类。', 'warn');
                return;
            }
            const cacheKey = `${category}_${keyword}_${limit}_${page}`;
            if (duoPageCache[cacheKey]) {
                const cached = duoPageCache[cacheKey];
                duoCache = cached.items;
                renderDuoResults(cached.items);
                if (pager) pager.innerText = `共 ${cached.total} 条，当前第 ${page} 页`;
                return;
            }
            const res = await fetch('/api/duo/resources/search', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({category, keyword, limit, offset})
            });
            const data = await res.json();
            const items = data.items || [];
            duoCache = items;
            duoPageCache[cacheKey] = {items, total: data.total || 0};
            renderDuoResults(items);
            if (pager) pager.innerText = `共 ${data.total || 0} 条，当前第 ${page} 页`;
        }

        function renderDuoResults(items) {
            const results = document.getElementById('duo_results');
            if (!results) return;
            if (!items.length) {
                results.innerHTML = '<div class="hint">无匹配资源</div>';
                return;
            }
            results.innerHTML = items.map((item, idx) => {
                const preview = item.preview ? `<img src="${item.preview}" style="width:36px;height:36px;vertical-align:middle;margin-right:6px;">` : '';
                return `<div class="resource-row">${preview}名称: ${item.name || ''} | 编号: ${item.id || ''} <button class="effect-add" type="button" onclick="useDuoResource(${idx})">使用</button></div>`;
            }).join('');
        }

        function duoPrevPage() {
            const pageInput = document.getElementById('duo_page');
            pageInput.value = Math.max(1, parseInt(pageInput.value || '1', 10) - 1);
            searchDuoResources();
        }

        function duoNextPage() {
            const pageInput = document.getElementById('duo_page');
            pageInput.value = parseInt(pageInput.value || '1', 10) + 1;
            searchDuoResources();
        }

        function clearDuoCache() {
            duoPageCache = {};
            const pager = document.getElementById('duo_pager_info');
            if (pager) pager.innerText = '';
        }

        async function refreshDuoCache() {
            const info = document.getElementById('duo_cache_info');
            const path = document.getElementById('duo_resource_path')?.value?.trim();
            const res = await fetch('/api/duo/cache/refresh', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({resource_path: path})
            });
            const data = await res.json();
            if (info) info.innerText = data.ok ? '资源列表已刷新' : (data.error || '刷新失败');
            duoPageCache = {};
            loadDuoCacheStatus();
        }

        async function loadDuoCacheStatus() {
            const info = document.getElementById('duo_cache_info');
            try {
                const res = await fetch('/api/duo/cache/status');
                const data = await res.json();
                if (info) info.innerText = data.exists ? `资源列表可用，共 ${data.resource_count || 0} 条` : '暂未发现已整理资源';
            } catch (e) {}
        }

        async function uploadDuoResources() {
            const fileInput = document.getElementById('duo_resource_file');
            if (!fileInput || !fileInput.files || !fileInput.files[0]) {
                notify('请先选择资源包文件。', 'warn');
                return;
            }
            const info = document.getElementById('duo_cache_info');
            const form = new FormData();
            form.append('file', fileInput.files[0]);
            const res = await fetch('/api/duo/resources/upload', {method: 'POST', body: form});
            const data = await res.json();
            if (info) info.innerText = data.ok ? `上传成功，共 ${data.count} 条资源` : (data.error || '上传失败');
            duoPageCache = {};
            loadDuoCacheStatus();
        }

        async function loadFfmpegStatus() {
            const info = document.getElementById('duo_ffmpeg_info');
            try {
                const res = await fetch('/api/duo/ffmpeg/status');
                const data = await res.json();
                if (info) info.innerText = data.ok ? `视频处理环境已连接：${data.path}` : (data.error || '视频处理环境未找到');
            } catch (e) {}
        }

        function syncDuoParamUI() {
            const blur = document.getElementById('duo_param_blur')?.checked;
            const shake = document.getElementById('duo_param_shake')?.checked;
            const beauty = document.getElementById('duo_param_beauty')?.checked;
            const intensity = parseFloat(document.getElementById('duo_param_intensity')?.value || '');
            const strength = parseFloat(document.getElementById('duo_param_strength')?.value || '');
            const speed = parseFloat(document.getElementById('duo_param_speed')?.value || '');
            const smooth = parseFloat(document.getElementById('duo_param_smooth')?.value || '');
            const whiten = parseFloat(document.getElementById('duo_param_whiten')?.value || '');
            const params = {};
            if (blur) params.blur = true;
            if (shake) params.shake = true;
            if (beauty) params.beauty = true;
            if (!isNaN(intensity)) params.intensity = intensity;
            if (!isNaN(strength)) params.strength = strength;
            if (!isNaN(speed)) params.speed = speed;
            if (!isNaN(smooth)) params.smooth = smooth;
            if (!isNaN(whiten)) params.whiten = whiten;
            const input = document.getElementById('duo_params');
            if (input) input.value = JSON.stringify(params);
        }

        function applyDuoPreset() {
            const preset = document.getElementById('duo_param_preset')?.value || '';
            if (preset === 'beauty') {
                document.getElementById('duo_param_beauty').checked = true;
                document.getElementById('duo_param_smooth').value = 0.6;
                document.getElementById('duo_param_whiten').value = 0.4;
            } else if (preset === 'shake') {
                document.getElementById('duo_param_shake').checked = true;
                document.getElementById('duo_param_intensity').value = 60;
            }
            syncDuoParamUI();
        }

        function syncDuoScale(source) {
            const num = document.getElementById('duo_scale');
            const slider = document.getElementById('duo_scale_slider');
            if (!num || !slider) return;
            if (source === 'num') slider.value = num.value || '1';
            else num.value = slider.value || '1';
        }

        function syncDuoRotation(source) {
            const num = document.getElementById('duo_rotation');
            const slider = document.getElementById('duo_rotation_slider');
            if (!num || !slider) return;
            if (source === 'num') slider.value = num.value || '0';
            else num.value = slider.value || '0';
        }

        function useDuoResource(idx) {
            const item = duoCache[idx];
            if (!item) return;
            const category = document.getElementById('duo_category').value;
            const indexes = parseIndexes(document.getElementById('duo_indexes')?.value || '');
            const paramsRaw = document.getElementById('duo_params')?.value || '';
            const paramsObj = parseMaybeJson(paramsRaw);
            const tr = document.getElementById('duo_timerange')?.value || '';
            const csRaw = document.getElementById('duo_clip_settings')?.value || '';
            const csObj = parseMaybeJson(csRaw);
            const intensity = parseFloat(document.getElementById('duo_intensity')?.value || '');
            const posRaw = document.getElementById('duo_position')?.value || '';
            const scale = parseFloat(document.getElementById('duo_scale')?.value || '');
            const rotation = parseFloat(document.getElementById('duo_rotation')?.value || '');

            const pack = {id: item.id, name: item.name, category};
            if (indexes) pack.indexes = indexes;
            if (paramsObj) pack.params = paramsObj;
            if (tr) pack.timerange = tr;
            if (csObj) pack.clip_settings = csObj;
            if (!isNaN(intensity)) pack.intensity = intensity;
            if (posRaw) pack.position = posRaw;
            if (!isNaN(scale)) pack.scale = scale;
            if (!isNaN(rotation)) pack.rotation = rotation;

            if (category.includes('text')) duoState.text_templates.push(pack);
            else if (category.includes('transition')) duoState.transitions.push(pack);
            else if (category.includes('face')) duoState.face_effects.push(pack);
            else if (category.includes('sticker')) duoState.stickers.push(pack);
            else duoState.video_effects.push(pack);

            renderDuoLists();
        }

        function buildDuoConfig() {
            const cfg = {
                text_templates: duoState.text_templates,
                video_effects: duoState.video_effects,
                transitions: duoState.transitions,
                face_effects: duoState.face_effects,
                stickers: duoState.stickers,
                green_screen: [],
                reverse: [],
                lut: [],
                text_styles: []
            };
            const gs = document.getElementById('duo_green_screen')?.value?.trim();
            const rv = document.getElementById('duo_reverse')?.value?.trim();
            const lut = document.getElementById('duo_lut')?.value?.trim();
            const ts = document.getElementById('duo_text_styles')?.value?.trim();
            try { if (gs) cfg.green_screen = JSON.parse(gs); } catch (e) { notify('绿幕设置格式不正确，已跳过这一项。', 'warn'); }
            try { if (rv) cfg.reverse = JSON.parse(rv); } catch (e) { notify('倒放设置格式不正确，已跳过这一项。', 'warn'); }
            try { if (lut) cfg.lut = JSON.parse(lut); } catch (e) { notify('LUT 设置格式不正确，已跳过这一项。', 'warn'); }
            try { if (ts) cfg.text_styles = JSON.parse(ts); } catch (e) { notify('文字样式设置格式不正确，已跳过这一项。', 'warn'); }
            const manual = document.getElementById('duo_manual_config')?.value?.trim();
            if (manual) {
                try {
                    const m = JSON.parse(manual);
                    for (const k of ['text_templates','video_effects','transitions','face_effects','stickers','green_screen','reverse','lut','text_styles']) {
                        if (Array.isArray(m[k])) cfg[k] = (cfg[k] || []).concat(m[k]);
                        else if (m[k] !== undefined) cfg[k] = m[k];
                    }
                } catch (e) { notify('补充设置格式不正确，已忽略这部分内容。', 'warn'); }
            }
            return cfg;
        }



        async function loadUserInfo() {
            const token = getToken();
            if (!token) {
                updateUserPanel(null);
                return;
            }
            try {
                const res = await authFetch('/api/user/info');
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || '登录信息获取失败');
                updateUserPanel(data.user);
            } catch (e) {
                forceLoggedOut('登录状态已失效，请重新登录');
                return;
            }
            toggleProtectedUI(!!getToken());
        }

        function initAuthUI() {
            const tabs = document.querySelectorAll('.auth-tab');
            const loginForm = document.getElementById('loginForm');
            const registerForm = document.getElementById('registerForm');
            const logoutBtn = document.getElementById('logoutBtn');
            const copyRefCodeBtn = document.getElementById('copyRefCodeBtn');
            const activateLicenseBtn = document.getElementById('activateLicenseBtn');
            const dailyCheckinBtn = document.getElementById('dailyCheckinBtn');
            const refreshPointsBtn = document.getElementById('refreshPointsBtn');
            const openBtns = [document.getElementById('openAuthModalBtnHero')].filter(Boolean);

            openBtns.forEach((btn) => btn.addEventListener('click', openAuthModal));
            document.querySelectorAll('[data-close-auth="true"]').forEach((el) => el.addEventListener('click', closeAuthModal));

            tabs.forEach(tab => {
                tab.addEventListener('click', () => {
                    tabs.forEach(t => t.classList.remove('active'));
                    tab.classList.add('active');
                    const target = tab.dataset.tab;
                    if (target === 'login') {
                        loginForm.style.display = 'flex';
                        registerForm.style.display = 'none';
                    } else {
                        loginForm.style.display = 'none';
                        registerForm.style.display = 'flex';
                    }
                    setAuthMessage('');
                });
            });

            loginForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const account = document.getElementById('loginAccount').value.trim();
                const password = document.getElementById('loginPassword').value;
                if (!account || !password) {
                    setAuthMessage('请输入账号和密码');
                    return;
                }
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: account, password})
                });
                const data = await res.json();
                if (data.ok) {
                    setToken(data.token);
                    setAuthMessage('登录成功', false);
                    updateUserPanel(data.user);
                    await Promise.all([loadAiProviders(), loadAiKeys()]);
                    closeAuthModal();
                    discoverDrafts();
                } else {
                    setAuthMessage(data.error || '登录失败');
                }
            });

            registerForm.addEventListener('submit', async (e) => {
                e.preventDefault();
                const username = document.getElementById('registerUsername').value.trim();
                const refCode = document.getElementById('registerRefCode')?.value?.trim().toUpperCase() || '';
                const password = document.getElementById('registerPassword').value;
                if (!username || !password) {
                    setAuthMessage('请输入用户名和密码');
                    return;
                }
                const res = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username, password, ref_code: refCode, auto_login: true})
                });
                const data = await res.json();
                if (data.ok) {
                    setToken(data.token || '');
                    setAuthMessage('注册成功', false);
                    updateUserPanel(data.user);
                    await Promise.all([loadAiProviders(), loadAiKeys()]);
                    closeAuthModal();
                    discoverDrafts();
                } else {
                    setAuthMessage(data.error || '注册失败');
                }
            });

            if (logoutBtn) {
                logoutBtn.addEventListener('click', () => {
                    forceLoggedOut('已退出登录');
                });
            }
            if (copyRefCodeBtn) {
                copyRefCodeBtn.addEventListener('click', copyRefCode);
            }
            if (activateLicenseBtn) {
                activateLicenseBtn.addEventListener('click', activateLicense);
            }
            if (dailyCheckinBtn) {
                dailyCheckinBtn.addEventListener('click', runDailyCheckin);
            }
            if (refreshPointsBtn) {
                refreshPointsBtn.addEventListener('click', loadPointsOverview);
            }
        }

        function initTheme() {
            const btn = document.getElementById('themeToggle');
            const saved = localStorage.getItem(themeKey) || 'light';
            if (saved === 'dark') document.body.classList.add('dark');
            if (btn) {
                btn.textContent = document.body.classList.contains('dark') ? '切换亮色' : '切换暗色';
                btn.addEventListener('click', () => {
                    document.body.classList.toggle('dark');
                    const mode = document.body.classList.contains('dark') ? 'dark' : 'light';
                    localStorage.setItem(themeKey, mode);
                    btn.textContent = mode === 'dark' ? '切换亮色' : '切换暗色';
                });
            }
        }

        async function selectSplitSourceFile() {
            const response = await fetch('/api/browse-file', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({file_types: ['.mp4', '.mov', '.avi', '.mkv', '.flv', '.wmv', '.m4v']})
            });
            const data = await response.json();
            if (data.path) {
                document.getElementById('split_source_path').value = data.path;
            } else if (data.file) {
                document.getElementById('split_source_path').value = data.file;
            }
        }

        async function selectSplitSourceFolder() {
            const response = await fetch('/api/browse-folder', {method: 'POST'});
            const data = await response.json();
            if (data.folder) {
                document.getElementById('split_source_path').value = data.folder;
            }
        }

        async function selectSplitOutput() {
            const response = await fetch('/api/browse-folder', {method: 'POST'});
            const data = await response.json();
            if (data.folder) {
                document.getElementById('split_output_dir').value = data.folder;
            }
        }

        async function selectSplitOutputFolder() {
            await selectSplitOutput();
        }

        async function selectSplitSubtitle() {
            const response = await fetch('/api/browse-file', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({file_types: ['.srt']})
            });
            const data = await response.json();
            if (data.path) {
                document.getElementById('split_subtitle_path').value = data.path;
            } else if (data.file) {
                document.getElementById('split_subtitle_path').value = data.file;
            }
        }

        async function selectSplitSubtitleFile() {
            await selectSplitSubtitle();
        }

        async function selectSettingsDraftRoot() {
            const response = await fetch('/api/browse-folder', {method: 'POST'});
            const data = await response.json();
            if (data.folder) {
                const input = document.getElementById('settingsDraftRoot');
                if (input) input.value = data.folder;
            }
        }

        async function selectExportFolder() {
            const response = await fetch('/api/browse-folder', {method: 'POST'});
            const data = await response.json();
            if (data.folder) {
                const input = document.getElementById('export_dir');
                if (input) input.value = data.folder;
            }
        }

        async function loadMaterialsList() {
            const summary = document.getElementById('materialsFolderSummary');
            const list = document.getElementById('materialsFolderList');
            if (!summary || !list) return;
            if (!getToken()) {
                summary.textContent = '请先登录后读取素材目录。';
                list.textContent = '登录后可查看本地素材目录。';
                return;
            }
            summary.textContent = '正在整理素材目录...';
            list.textContent = '正在整理，请稍候...';
            try {
                const res = await authFetch('/api/materials/list');
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '读取失败');
                }
                const items = Array.isArray(data.items) ? data.items : [];
                summary.textContent = data.folder ? `素材目录：${data.folder}` : '尚未配置素材目录';
                list.textContent = items.length ? items.slice(0, 30).join('\n') : '当前素材目录暂无可用素材。';
            } catch (e) {
                summary.textContent = `读取素材目录失败：${e.message || e}`;
                list.textContent = '读取失败。';
            }
        }

        async function loadUserMaterials() {
            const summary = document.getElementById('userMaterialsSummary');
            const list = document.getElementById('userMaterialsList');
            if (!summary || !list) return;
            if (!getToken()) {
                summary.textContent = '请先登录后读取个人素材库。';
                list.textContent = '登录后可查看个人素材库。';
                return;
            }
            summary.textContent = '正在整理个人素材库...';
            list.textContent = '正在整理，请稍候...';
            try {
                const res = await authFetch('/api/user/materials');
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '读取失败');
                }
                const items = Array.isArray(data.items) ? data.items : [];
                summary.textContent = `已同步 ${items.length} 个素材`;
                list.textContent = items.length
                    ? items.slice(0, 30).map((item) => {
                        const name = item.file_path?.split(/[\\/]/).pop() || item.file_path || '未命名素材';
                        const projectName = item.metadata?.project_name || '';
                        const projectId = item.metadata?.project_id || '';
                        const projectPart = projectName || projectId ? ` / ${projectName || projectId}` : '';
                        return `ID:${item.id || '-'} ${name} [${item.file_type || '-'} / ${item.source || '-'}${projectPart}]`;
                    }).join('\n')
                    : '个人素材库为空。';
            } catch (e) {
                summary.textContent = `读取个人素材库失败：${e.message || e}`;
                list.textContent = '读取失败。';
            }
        }

async function refreshUserMaterials() {
    const summary = document.getElementById('userMaterialsSummary');
    if (summary) summary.textContent = '正在同步新素材...';
            try {
                const res = await authFetch('/api/user/materials/refresh', {method: 'POST'});
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '同步失败');
                }
                await loadUserMaterials();
                if (summary) summary.textContent = `同步完成，本次新增 ${data.added || 0} 个素材`;
            } catch (e) {
        if (summary) summary.textContent = `同步失败：${e.message || e}`;
    }
}

async function renameUserMaterialProject() {
    const projectId = document.getElementById('materials_project_id')?.value?.trim() || '';
    const projectName = document.getElementById('materials_project_name')?.value?.trim() || '';
    const box = document.getElementById('materials_project_status');
    if (!projectId || !projectName) {
        if (box) box.textContent = '请先填写项目编号和新项目名称。';
        return;
    }
    const res = await authFetch('/api/user/materials/project/rename', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({project_id: projectId, project_name: projectName})
    });
    const data = await res.json();
    if (box) box.textContent = data.ok ? `已更新 ${data.updated || 0} 个素材的项目名称。` : (data.error || '项目改名失败');
    if (data.ok) {
        await loadUserMaterials();
        await refreshAiMaterials();
    }
}

        async function loadWorkspaceSettingsConfig() {
            const res = await authFetch('/api/workspace/settings');
            const data = await res.json();
            if (!res.ok || data.ok === false) {
                throw new Error(data.error || '设置加载失败');
            }
            const settings = data.settings || {};
            cacheWorkspaceSettingsConfig(settings);
            syncWorkspacePathInputs();
            return settings;
        }

        async function saveWorkspaceSettingsConfig(payload) {
            const res = await authFetch('/api/workspace/settings', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload || {})
            });
            const data = await res.json();
            if (!res.ok || data.ok === false) {
                throw new Error(data.error || '设置保存失败');
            }
            const settings = data.settings || {};
            cacheWorkspaceSettingsConfig(settings);
            syncWorkspacePathInputs();
            return settings;
        }

        async function initSettingsWorkspace() {
            const saveMsg = document.getElementById('settingsSaveMsg');
            const pathSaveMsg = document.getElementById('pathSettingsSaveMsg');
            const serviceSaveMsg = document.getElementById('serviceSettingsSaveMsg');
            const openclawStatusMsg = document.getElementById('openclawSettingsStatus');
            const strategyInput = document.getElementById('settingsStrategy');
            const autoDiscoverInput = document.getElementById('settingsAutoDiscover');
            const autoLoadInput = document.getElementById('settingsAutoLoadLastDraft');
            const materialFolderInput = document.getElementById('settingsMaterialFolder');
            const draftsFolderInput = document.getElementById('settingsDraftsFolder');
            const audioFolderInput = document.getElementById('settingsAudioFolder');
            const exportDirInput = document.getElementById('settingsDefaultExportDir');
            const openclawBaseUrlInput = document.getElementById('settingsOpenclawBaseUrl');
            const openclawTokenInput = document.getElementById('settingsOpenclawToken');

            try {
                const localSettings = getWorkspaceSettings();
                const settings = await loadWorkspaceSettingsConfig();
                const workspace = settings.workspace || {};
                const paths = settings.paths || {};
                const services = settings.services || {};
                const openclaw = services.openclaw || {};

                if (strategyInput) strategyInput.value = workspace.strategy || localSettings.strategy || 'simple';
                if (autoDiscoverInput) autoDiscoverInput.checked = workspace.auto_discover !== false;
                if (autoLoadInput) autoLoadInput.checked = !!workspace.auto_load_last_draft;
                if (materialFolderInput) materialFolderInput.value = paths.material_folder || '';
                if (draftsFolderInput) draftsFolderInput.value = paths.drafts_folder || '';
                if (audioFolderInput) audioFolderInput.value = paths.audio_folder || '';
                if (exportDirInput) exportDirInput.value = paths.default_export_dir || '';
                if (openclawBaseUrlInput) openclawBaseUrlInput.value = openclaw.base_url || 'http://localhost:18789';
                if (openclawTokenInput) openclawTokenInput.value = openclaw.token || '';

                setWorkspaceSettings({
                    strategy: workspace.strategy || localSettings.strategy || 'simple',
                    auto_discover: workspace.auto_discover !== false,
                    auto_load_last_draft: !!workspace.auto_load_last_draft
                });
                syncWorkspacePathInputs();
            } catch (e) {
                setInlineMessage(saveMsg, `设置加载失败：${e.message || e}`, 'error');
            }

            document.getElementById('saveSettingsBtn')?.addEventListener('click', async () => {
                try {
                    const payload = {
                        workspace: {
                            strategy: strategyInput?.value || 'simple',
                            auto_discover: !!autoDiscoverInput?.checked,
                            auto_load_last_draft: !!autoLoadInput?.checked
                        }
                    };
                    await saveWorkspaceSettingsConfig(payload);
                    setWorkspaceSettings(payload.workspace);
                    setInlineMessage(saveMsg, '工作台设置已保存', 'success');
                    notify('工作台设置已保存', 'success');
                    if (payload.workspace.auto_discover && getToken()) discoverDrafts();
                } catch (e) {
                    const message = `保存失败：${e.message || e}`;
                    setInlineMessage(saveMsg, message, 'error');
                    notify(message, 'error');
                }
            });

            document.getElementById('savePathSettingsBtn')?.addEventListener('click', async () => {
                try {
                    const payload = {
                        paths: {
                            material_folder: materialFolderInput?.value?.trim() || '',
                            drafts_folder: draftsFolderInput?.value?.trim() || '',
                            audio_folder: audioFolderInput?.value?.trim() || '',
                            default_export_dir: exportDirInput?.value?.trim() || ''
                        }
                    };
                    await saveWorkspaceSettingsConfig(payload);
                    setInlineMessage(pathSaveMsg, '路径设置已保存', 'success');
                    notify('路径设置已保存', 'success');
                } catch (e) {
                    const message = `保存失败：${e.message || e}`;
                    setInlineMessage(pathSaveMsg, message, 'error');
                    notify(message, 'error');
                }
            });

            document.getElementById('saveServiceSettingsBtn')?.addEventListener('click', async () => {
                try {
                    const payload = {
                        services: {
                            openclaw: {
                                base_url: openclawBaseUrlInput?.value?.trim() || '',
                                token: openclawTokenInput?.value?.trim() || ''
                            }
                        }
                    };
                    await saveWorkspaceSettingsConfig(payload);
                    setInlineMessage(serviceSaveMsg, 'AI 漫剧服务已保存', 'success');
                    notify('AI 漫剧服务已保存', 'success');
                } catch (e) {
                    const message = `保存失败：${e.message || e}`;
                    setInlineMessage(serviceSaveMsg, message, 'error');
                    notify(message, 'error');
                }
            });

            document.getElementById('testOpenclawSettingsBtn')?.addEventListener('click', async () => {
                try {
                    const base_url = openclawBaseUrlInput?.value?.trim() || '';
                    const token = openclawTokenInput?.value?.trim() || '';
                    const res = await authFetch('/api/openclaw/test', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({base_url, token})
                    });
                    const data = await res.json();
                    const message = data.ok ? 'AI 漫剧服务连接成功' : (data.error || '连接失败');
                    setInlineMessage(openclawStatusMsg, message, data.ok ? 'success' : 'error');
                    notify(message, data.ok ? 'success' : 'warn');
                } catch (e) {
                    const message = `连接失败：${e.message || e}`;
                    setInlineMessage(openclawStatusMsg, message, 'error');
                    notify(message, 'error');
                }
            });
        }

        function getSplitDom() {
            return {
                mode: document.getElementById('split_mode'),
                sourcePath: document.getElementById('split_source_path'),
                outputDir: document.getElementById('split_output_dir'),
                segmentSeconds: document.getElementById('split_segment_seconds'),
                splitCount: document.getElementById('split_count'),
                threshold: document.getElementById('split_threshold'),
                minSceneLen: document.getElementById('split_min_scene_len'),
                silenceDb: document.getElementById('split_silence_db'),
                minSilence: document.getElementById('split_min_silence'),
                subtitlePath: document.getElementById('split_subtitle_path'),
                buildDraft: document.getElementById('split_build_draft'),
                resultBox: document.getElementById('split_result'),
                status: document.getElementById('split_status'),
                hint: document.getElementById('split_mode_hint')
            };
        }

        function updateSplitModeUI() {
            const splitDom = getSplitDom();
            const mode = splitDom.mode?.value || 'fixed';
            const fields = document.querySelectorAll('.split-mode-field');
            fields.forEach((field) => {
                const raw = field.getAttribute('data-mode') || '';
                const modes = raw.split(',').map(v => v.trim()).filter(Boolean);
                field.style.display = modes.includes(mode) ? 'block' : 'none';
            });

            const hints = {
                fixed: '固定时长切分，适合快速均匀拆分。',
                count: '按目标份数平均拆分。',
                scene: '基于场景变化自动拆分，需要场景检测依赖。',
                silence: '基于静音区间拆分，适合口播或音频主导内容。',
                subtitle: '根据字幕时间轴切分，需要 .srt 文件。'
            };
            if (splitDom.hint) splitDom.hint.textContent = hints[mode] || '';
        }

        async function startSplit() {
            const splitDom = getSplitDom();
            const sourcePath = splitDom.sourcePath?.value?.trim();
            const outputDir = splitDom.outputDir?.value?.trim();
            const mode = splitDom.mode?.value || 'fixed';
            const segmentSeconds = parseFloat(splitDom.segmentSeconds?.value || '0');
            const splitCount = parseInt(splitDom.splitCount?.value || '0', 10);
            const threshold = parseFloat(splitDom.threshold?.value || '30');
            const minSceneLen = parseInt(splitDom.minSceneLen?.value || '15', 10);
            const silenceDb = parseFloat(splitDom.silenceDb?.value || '-35');
            const minSilence = parseFloat(splitDom.minSilence?.value || '0.4');
            const subtitlePath = splitDom.subtitlePath?.value?.trim();
            const buildDraft = splitDom.buildDraft?.checked || false;
            const resultBox = splitDom.resultBox;
            const status = splitDom.status;

            if (!getToken()) {
                if (status) status.textContent = '请先登录';
                if (resultBox) resultBox.innerText = '登录后才能使用分割功能。';
                return;
            }
            if (!sourcePath || !outputDir) {
                if (status) status.textContent = '参数不足';
                if (resultBox) resultBox.innerText = '请先选择输入路径和输出目录。';
                return;
            }
            if (mode === 'count' && (!splitCount || splitCount <= 0)) {
                if (status) status.textContent = '参数不足';
                if (resultBox) resultBox.innerText = '按数量模式需要填写分割份数。';
                return;
            }
            if (mode === 'subtitle' && !subtitlePath) {
                if (status) status.textContent = '参数不足';
                if (resultBox) resultBox.innerText = '字幕分割需要选择 .srt 文件。';
                return;
            }

            if (status) status.textContent = '分割中...';
            if (resultBox) resultBox.innerText = '正在分割，请稍候...';

            try {
                const res = await authFetch('/api/split', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        source_path: sourcePath,
                        output_dir: outputDir,
                        mode,
                        segment_seconds: segmentSeconds,
                        split_count: splitCount,
                        threshold,
                        min_scene_len: minSceneLen,
                        silence_db: silenceDb,
                        min_silence: minSilence,
                        subtitle_path: subtitlePath,
                        build_draft: buildDraft
                    })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '分割失败，请检查参数或路径。');
                }

                const lines = [];
                (data.results || []).forEach((item) => {
                    const parts = Array.isArray(item.parts) ? item.parts.length : 0;
                    const draftName = item.draft_name ? `，草稿：${item.draft_name}` : '';
                    const error = item.error ? `，错误：${item.error}` : '';
                    lines.push(`${item.file} -> ${parts} 段${draftName}${error}`);
                });

                if (status) status.textContent = '分割完成';
                if (resultBox) resultBox.innerText = lines.join('\n') || '分割完成。';
            } catch (e) {
                if (status) status.textContent = '分割失败';
                if (resultBox) resultBox.innerText = `分割失败: ${e.message || e}`;
            }
        }

        async function runDraftBatchExport() {
            const exportDir = document.getElementById('export_dir')?.value?.trim();
            const exportFormat = document.getElementById('export_format')?.value || 'mp4';
            const exportResolution = document.getElementById('export_resolution')?.value || '1080p';
            const exportFps = parseInt(document.getElementById('export_fps')?.value || '30', 10);
            if (!getToken()) {
                setToolResult('export_result', '请先登录后再执行批量导出。');
                return;
            }
            if (!exportDraftQueue.length) {
                setToolResult('export_result', '请先加入至少一个待导出草稿。');
                return;
            }
            if (!exportDir) {
                setToolResult('export_result', '请先选择导出目录。');
                return;
            }
            setToolResult('export_result', '正在批量导出草稿，请稍候...');
            try {
                const res = await authFetch('/api/export/drafts', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        draft_paths: exportDraftQueue.map((item) => item.path),
                        output_dir: exportDir,
                        export_format: exportFormat,
                        export_resolution: exportResolution,
                        export_fps: exportFps
                    })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '多草稿导出失败');
                }
                const lines = [
                    `导出目录：${data.output_dir || exportDir}`,
                    `执行结果：成功 ${data.success_count || 0} / 共 ${data.total || exportDraftQueue.length} 个`
                ];
                (data.results || []).forEach((item) => {
                    if (item.ok) {
                        lines.push(`已导出：${item.draft_name} -> ${item.exported_draft_name || '新草稿'}`);
                    } else {
                        lines.push(`失败：${item.draft_name} -> ${item.error || '未知错误'}`);
                    }
                });
                setToolResult('export_result', lines.join('\n'));
            } catch (e) {
                setToolResult('export_result', `批量导出失败：${e.message || e}`);
            }
        }

        async function exportMainTrackSegments() {
            const draftPath = getDraftElement('path')?.value?.trim() || currentDraftPath || '';
            const exportDir = document.getElementById('export_dir')?.value?.trim();
            if (!getToken()) {
                setToolResult('export_result', '请先登录后再导出主视频片段。');
                return;
            }
            if (!draftPath || !currentDraftPath || currentDraftPath !== draftPath) {
                setToolResult('export_result', '请先读取当前草稿，再导出主视频片段。');
                return;
            }
            if (!exportDir) {
                setToolResult('export_result', '请先选择导出目录。');
                return;
            }
            setToolResult('export_result', '正在导出主视频片段，请稍候...');
            try {
                const res = await authFetch('/api/export/main-track', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        draft_path: draftPath,
                        output_dir: exportDir
                    })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '主视频片段导出失败');
                }
                const lines = [
                    `视频轨道：${data.track_name || '主视频轨道'}`,
                    `导出目录：${data.output_dir || exportDir}`,
                    `成功导出：${data.exported || 0} 个片段`
                ];
                (data.results || []).slice(0, 20).forEach((item) => {
                    lines.push(item.ok ? `片段 ${item.index}：${item.output}` : `片段 ${item.index} 失败：${item.error || '未知错误'}`);
                });
                if ((data.results || []).length > 20) {
                    lines.push(`其余 ${data.results.length - 20} 个结果已省略显示。`);
                }
                setToolResult('export_result', lines.join('\n'));
            } catch (e) {
                setToolResult('export_result', `主视频片段导出失败：${e.message || e}`);
            }
        }

        async function analyzeSplitDraft() {
            const draftPath = getDraftElement('path')?.value?.trim() || currentDraftPath || '';
            if (!getToken()) {
                setToolResult('split_draft_result', '请先登录后再查看草稿内容结构。');
                return;
            }
            if (!draftPath || !currentDraftPath || currentDraftPath !== draftPath) {
                setToolResult('split_draft_result', '请先读取当前草稿。');
                return;
            }
            setToolResult('split_draft_result', '正在查看当前草稿的内容结构...');
            try {
                const res = await authFetch('/api/draft/timeline-summary', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({draft_path: draftPath})
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '读取失败');
                }
                const lines = [
                    `草稿：${data.draft_name || draftPath}`,
                    `视频轨道：${(data.video_tracks || []).length} 条`,
                    ...((data.video_tracks || []).map((item, idx) => `视频轨道 ${idx + 1}：${item.name || 'video'} / ${item.segment_count || 0} 段 / ${item.total_duration || 0}s`)),
                    `主视频片段：${(data.main_track_segments || []).length} 段`,
                    `字幕片段：${(data.text_segments || []).length} 段`
                ];
                (data.main_track_segments || []).slice(0, 10).forEach((item) => {
                    lines.push(`主视频片段 ${item.index}：${item.material_name || '未命名素材'} / 时间轴 ${item.timeline_start}s + ${item.timeline_duration}s`);
                });
                if ((data.text_segments || []).length) {
                    const preview = (data.text_segments || []).slice(0, 5).map((item) => `字幕 ${item.index}：${item.start}s + ${item.duration}s / ${item.text || ''}`);
                    lines.push(...preview);
                }
                setToolResult('split_draft_result', lines.join('\n'));
            } catch (e) {
                setToolResult('split_draft_result', `查看草稿结构失败：${e.message || e}`);
            }
        }

        async function analyzeSplitDraftQueue() {
            if (!getToken()) {
                setToolResult('split_multi_result', '请先登录后再查看多草稿内容结构。');
                return;
            }
            if (!splitDraftQueue.length) {
                setToolResult('split_multi_result', '请先加入要查看的草稿。');
                return;
            }
            setToolResult('split_multi_result', '正在查看多份草稿的内容结构...');
            try {
                const res = await authFetch('/api/drafts/timeline-summary', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({draft_paths: splitDraftQueue.map((item) => item.path)})
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '读取失败');
                }
                const lines = [];
                (data.items || []).forEach((item) => {
                    if (item.ok) {
                        lines.push(`${item.draft_name}：视频轨道 ${item.video_track_count || 0} 条 / 字幕轨道 ${item.text_track_count || 0} 条 / 主视频片段 ${item.main_track_segments || 0} 段`);
                    } else {
                        lines.push(`${item.draft_name}：读取失败 -> ${item.error || '未知错误'}`);
                    }
                });
                setToolResult('split_multi_result', lines.join('\n'));
            } catch (e) {
                setToolResult('split_multi_result', `批量查看草稿结构失败：${e.message || e}`);
            }
        }

        async function splitDraftMainTrack() {
            const draftPath = getDraftElement('path')?.value?.trim() || currentDraftPath || '';
            const outputDir = document.getElementById('split_draft_output_dir')?.value?.trim() || '';
            const segmentSeconds = parseFloat(document.getElementById('split_draft_segment_seconds')?.value || '0');
            if (!getToken()) {
                setToolResult('split_draft_result', '请先登录后再执行主视频定长分割。');
                return;
            }
            if (!draftPath || !currentDraftPath || currentDraftPath !== draftPath) {
                setToolResult('split_draft_result', '请先读取当前草稿。');
                return;
            }
            if (!(segmentSeconds > 0)) {
                setToolResult('split_draft_result', '请输入有效的分割时长。');
                return;
            }
            setToolResult('split_draft_result', '正在执行主视频定长分割...');
            try {
                const res = await authFetch('/api/draft/split-main-track', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        draft_path: draftPath,
                        output_dir: outputDir,
                        segment_seconds: segmentSeconds
                    })
                });
                const data = await res.json();
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '主视频定长分割失败');
                }
                const lines = [
                    `新草稿：${data.draft_name || '-'}`,
                    `输出目录：${data.output || outputDir || '-'}`,
                    `分割时长：${data.segment_seconds || segmentSeconds}s`,
                    `生成片段：${data.generated || 0} 段`
                ];
                (data.results || []).slice(0, 20).forEach((item) => {
                    if (item.ok) {
                        lines.push(`原片段 ${item.segment_index} / 子段 ${item.piece_index}：${item.target_range}`);
                    } else {
                        lines.push(`原片段 ${item.segment_index} / 子段 ${item.piece_index || '-'} 失败：${item.error || '未知错误'}`);
                    }
                });
                if ((data.results || []).length > 20) {
                    lines.push(`其余 ${data.results.length - 20} 条结果已省略显示。`);
                }
                setToolResult('split_draft_result', lines.join('\n'));
            } catch (e) {
                setToolResult('split_draft_result', `主视频定长分割失败：${e.message || e}`);
            }
        }

        async function selectSplitDraftOutputFolder() {
            try {
                const response = await fetch('/api/browse-folder', {method: 'POST'});
                const data = await response.json();
                if (data.folder) {
                    const input = document.getElementById('split_draft_output_dir');
                    if (input) input.value = data.folder;
                }
            } catch (e) {
                setToolResult('split_draft_result', `选择输出目录失败：${e.message || e}`);
            }
        }

        function initDraftWorkspace() {
            document.getElementById('folder_path')?.addEventListener('input', updatePrimaryActionState);
            document.getElementById('folder_path')?.addEventListener('change', (event) => {
                const value = event.target?.value?.trim();
                if (value) {
                    pushRecentMaterialFolder(value);
                    setWorkspaceSettings({last_materials_root: value});
                }
            });
            getAllDraftShells().forEach((shell) => {
                const selectedBar = shell.querySelector('.draft-selected-bar');
                const versionField = getDraftElement('version', shell)?.closest('.form-group');
                if (versionField) versionField.style.display = 'none';
                const pathField = getDraftElement('path', shell)?.closest('.form-group');
                if (pathField) pathField.classList.add('full');
                const readBtn = selectedBar?.querySelector('button[onclick="loadDraftInfo()"]');
                if (readBtn) readBtn.remove();
                if (selectedBar && !selectedBar.querySelector('.draft-picker-trigger')) {
                    const trigger = document.createElement('button');
                    trigger.type = 'button';
                    trigger.className = 'draft-picker-trigger';
                    trigger.textContent = '选择草稿';
                    trigger.addEventListener('click', () => openDraftPicker(shell));
                    selectedBar.appendChild(trigger);
                }
                getDraftElement('path', shell)?.addEventListener('input', () => {
                    updatePrimaryActionState();
                    updateWorkspaceDraftBadge();
                });
            });
            getDraftRefreshButtons().forEach((button) => {
                button.addEventListener('click', () => openDraftPicker(button.closest('[data-draft-shell="true"]')));
            });
            document.getElementById('draftPickerRefreshBtn')?.addEventListener('click', () => discoverDrafts(activeDraftShell, true));
            document.querySelectorAll('[data-close-draft-picker="true"]').forEach((el) => {
                el.addEventListener('click', closeDraftPicker);
            });
            document.getElementById('closeDraftPickerBtn')?.addEventListener('click', closeDraftPicker);

            const settings = getWorkspaceSettings();
            if (settings.last_draft_version) {
                currentDraftVersion = settings.last_draft_version;
            }
            if (settings.auto_load_last_draft && settings.last_draft_path) {
                currentDraftPath = settings.last_draft_path;
                updateWorkspaceDraftBadge();
            }
            syncWorkspacePathInputs();
            syncDraftShellValues();
            renderRecentMaterialFolders();
            renderExportDraftQueue();
            renderSplitDraftQueue();
            updateMixModeUI();
        }

        function getDirectSubtabs(root) {
            if (!root || !root.children) return null;
            return Array.from(root.children).find((node) => node instanceof HTMLElement && node.classList.contains('subtabs')) || null;
        }

        const WORKSPACE_NAV_CONFIG = {
            mix: {
                panelId: 'panel-materials',
                defaultItem: 'group',
                items: {
                    group: {kind: 'mix', focusId: 'mix-mode-group-anchor', mixTarget: 'group'},
                    mix: {kind: 'mix', focusId: 'mix-mode-mix-anchor', mixTarget: 'mix'},
                    partition: {kind: 'mix', focusId: 'mix-mode-partition-anchor', mixTarget: 'partition'}
                }
            },
            ai: {
                panelId: 'panel-ai-make',
                defaultItem: 'make',
                items: {
                    make: {kind: 'panel', panelId: 'panel-ai-make'},
                    manga: {kind: 'panel', panelId: 'panel-ai-manga'}
                }
            },
            effects: {
                panelId: 'panel-effects',
                defaultItem: 'effects-core',
                items: {
                    'effects-core': {kind: 'subtab', containerId: 'effects_section', target: 'effects-core'},
                    'effects-resource': {kind: 'subtab', containerId: 'effects_section', target: 'effects-resource'},
                    'effects-duo': {kind: 'subtab', containerId: 'effects_section', target: 'effects-duo'}
                }
            },
            split: {
                panelId: 'panel-split',
                defaultItem: 'split-file',
                items: {
                    'split-file': {kind: 'subtab', containerId: 'panel-split', target: 'split-file'},
                    'split-draft': {kind: 'subtab', containerId: 'panel-split', target: 'split-draft'},
                    'split-batch': {kind: 'subtab', containerId: 'panel-split', target: 'split-batch'}
                }
            },
            clip: {
                panelId: 'panel-clip',
                defaultItem: 'clip-ai',
                items: {
                    'clip-ai': {kind: 'subtab', containerId: 'clipToolsGrid', target: 'clip-ai'},
                    'clip-rhythm': {kind: 'subtab', containerId: 'clipToolsGrid', target: 'clip-rhythm'},
                    'clip-transform': {kind: 'subtab', containerId: 'clipToolsGrid', target: 'clip-transform'},
                    'clip-shake': {kind: 'subtab', containerId: 'clipToolsGrid', target: 'clip-shake'}
                }
            },
            export: {
                panelId: 'panel-export',
                defaultItem: 'export-settings',
                items: {
                    'export-settings': {kind: 'subtab', containerId: 'panel-export', target: 'export-settings'},
                    'export-batch': {kind: 'subtab', containerId: 'panel-export', target: 'export-batch'},
                    'export-segments': {kind: 'subtab', containerId: 'panel-export', target: 'export-segments'}
                }
            },
            settings: {
                panelId: 'panel-settings',
                defaultItem: 'settings-basic-section',
                items: {
                    'settings-basic-section': {kind: 'section', sectionId: 'settings-basic-section'},
                    'settings-path-section': {kind: 'section', sectionId: 'settings-path-section'},
                    'settings-service-section': {kind: 'section', sectionId: 'settings-service-section'},
                    'settings-ai-section': {kind: 'section', sectionId: 'settings-ai-section'}
                }
            },
            account: {
                panelId: 'panel-account',
                defaultItem: 'account-profile-section',
                items: {
                    'account-profile-section': {kind: 'section', sectionId: 'account-profile-section'},
                    'account-license-section': {kind: 'section', sectionId: 'account-license-section'}
                }
            }
        };

        let activeWorkspaceNav = {group: 'mix', item: 'group'};

        function getWorkspaceNavGroup(groupKey) {
            return groupKey ? WORKSPACE_NAV_CONFIG[groupKey] || null : null;
        }

        function getWorkspaceNavItem(groupKey, itemKey) {
            const group = getWorkspaceNavGroup(groupKey);
            if (!group) return null;
            const resolvedItemKey = itemKey || group.defaultItem;
            const item = resolvedItemKey ? group.items?.[resolvedItemKey] || null : null;
            if (!item) return null;
            return {
                groupKey,
                itemKey: resolvedItemKey,
                panelId: item.panelId || group.panelId,
                ...item
            };
        }

        function syncWorkspaceSidebarState(groupKey, itemKey, options = {}) {
            const keepOpen = options.openActiveGroup !== false;
            document.querySelectorAll('.sidebar-group').forEach((group) => {
                const isActiveGroup = group.dataset.group === groupKey;
                group.classList.toggle('active', isActiveGroup);
                if (keepOpen) {
                    group.classList.toggle('open', isActiveGroup);
                }
            });
            document.querySelectorAll('.sidebar-link[href^="#"]').forEach((link) => {
                const linkGroup = link.dataset.navGroup || link.closest('.sidebar-group')?.dataset.group || '';
                const linkItem = link.dataset.navItem || '';
                link.classList.toggle('active', linkGroup === groupKey && linkItem === itemKey);
            });
        }

        function applyWorkspaceNavigation(groupKey, itemKey = '', options = {}) {
            const entry = getWorkspaceNavItem(groupKey, itemKey);
            if (!entry) return;
            const targetPanel = document.getElementById(entry.panelId);
            if (!targetPanel) return;

            activeWorkspaceNav = {group: entry.groupKey, item: entry.itemKey};
            document.querySelectorAll('.workspace-panel').forEach((panel) => {
                panel.classList.toggle('active', panel.id === entry.panelId);
            });
            syncWorkspaceSidebarState(entry.groupKey, entry.itemKey, options);

            syncDraftShellValues();
            if (targetPanel.dataset.requiresDraft === 'true') {
                discoverDrafts();
            }

            if (entry.kind === 'mix') {
                setMixStrategy(entry.mixTarget || entry.itemKey);
            }
            if (entry.kind === 'subtab') {
                activateSecondaryTab(entry.containerId || entry.panelId, entry.target);
            }
            if (entry.kind === 'section') {
                activateHardSection(entry.panelId, entry.sectionId);
            }

            const shouldScroll = options.scroll !== false;
            const scrollTarget = entry.focusId ? document.getElementById(entry.focusId) : targetPanel;
            if (shouldScroll && scrollTarget) {
                scrollTarget.scrollIntoView({behavior: 'smooth', block: 'start'});
            }
        }

        function resolveWorkspaceNavFromLink(link) {
            if (!(link instanceof HTMLElement)) return null;
            const groupKey = link.closest('.sidebar-group')?.dataset.group || '';
            const group = getWorkspaceNavGroup(groupKey);
            if (!group) return null;

            const href = link.getAttribute('href') || '';
            const mixTarget = link.dataset.mixTarget || '';
            const subtabTarget = link.dataset.subtabTarget || '';
            const hardSection = link.dataset.hardSection || '';

            const matched = Object.entries(group.items || {}).find(([, item]) => {
                if (item.kind === 'mix') return item.mixTarget === mixTarget;
                if (item.kind === 'subtab') return item.target === subtabTarget;
                if (item.kind === 'section') return item.sectionId === hardSection;
                if (item.kind === 'panel') return href === `#${item.panelId || group.panelId}`;
                return false;
            });
            if (!matched) return null;
            return {groupKey, itemKey: matched[0]};
        }

        function annotateWorkspaceSidebarLinks() {
            document.querySelectorAll('.sidebar-link[href^="#"]').forEach((link) => {
                const resolved = resolveWorkspaceNavFromLink(link);
                if (!resolved) return;
                link.dataset.navGroup = resolved.groupKey;
                link.dataset.navItem = resolved.itemKey;
            });
        }

        function openWorkspaceSettingsSection(sectionId = 'settings-service-section') {
            applyWorkspaceNavigation('settings', sectionId, {openActiveGroup: true});
        }

        async function browseWorkspaceFolder(inputId) {
            try {
                const res = await fetch('/api/browse-folder', {method: 'POST'});
                const data = await res.json();
                if (!data.folder) return;
                const input = document.getElementById(inputId);
                if (input) input.value = data.folder;
            } catch (e) {}
        }

        function inferSubtabDisplay(node) {
            if (!(node instanceof HTMLElement)) return 'block';
            if (node.classList.contains('tool-grid') || node.classList.contains('tool-grid-3')) return 'grid';
            if (node.classList.contains('draft-list-grid')) return 'grid';
            if (node.classList.contains('module-subsection')) return 'block';
            if (node.classList.contains('tool-card')) return 'block';
            if (node.classList.contains('flow-card')) return 'block';
            return 'block';
        }

        function initSecondaryTabs(panelId, items = [], options = {}) {
            const panel = document.getElementById(panelId);
            const root = options.rootId ? document.getElementById(options.rootId) : panel;
            if (!panel || !root || getDirectSubtabs(root)) return;
            const cards = typeof options.getNodes === 'function'
                ? options.getNodes(root, panel)
                : Array.from(root.children).filter((node) => {
                    if (!(node instanceof HTMLElement)) return false;
                    if (node.classList.contains('tool-card') || node.classList.contains('flow-card') || node.classList.contains('tool-grid') || node.classList.contains('module-subsection')) return true;
                    return !!(options.includeInlineActions && node.classList.contains('inline-actions'));
                });
            if (!cards.length || !items.length) return;
            const taggedCards = cards.filter((node) => node instanceof HTMLElement && node.dataset.subtabGroup);
            const nav = document.createElement('div');
            nav.className = 'subtabs';
            nav.dataset.tabHost = root.id || panelId;
            items.forEach((item, index) => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = `subtab-btn${index === 0 ? ' active' : ''}`;
                button.textContent = item.label;
                button.dataset.target = item.id;
                nav.appendChild(button);

                const itemNodes = taggedCards.length
                    ? taggedCards.filter((node) => node.dataset.subtabGroup === item.id)
                    : (item.indexes || []).map((cardIndex) => cards[cardIndex]).filter(Boolean);

                itemNodes.forEach((node) => {
                    if (!node) return;
                    node.classList.add('subtab-panel');
                    node.dataset.subtabDisplay = inferSubtabDisplay(node);
                    if (index === 0) node.classList.add('active');
                    node.dataset.subtab = item.id;
                    node.style.display = index === 0 ? node.dataset.subtabDisplay : 'none';
                });
            });
            const insertTarget = taggedCards[0] || cards[0];
            if (!insertTarget) return;
            root.insertBefore(nav, insertTarget);
            nav.querySelectorAll('.subtab-btn').forEach((button) => {
                button.addEventListener('click', () => {
                    activateSecondaryTab(root.id || panelId, button.dataset.target);
                });
            });
            const activeItem = activeWorkspaceNav?.group ? getWorkspaceNavItem(activeWorkspaceNav.group, activeWorkspaceNav.item) : null;
            if (activeItem?.kind === 'subtab' && (activeItem.containerId || activeItem.panelId) === (root.id || panelId)) {
                activateSecondaryTab(root.id || panelId, activeItem.target);
                return;
            }
            activateDefaultSecondaryTab(root.id || panelId);
        }

        function activateSecondaryTab(containerId, target) {
            if (!containerId || !target) return;
            const root = document.getElementById(containerId);
            if (!root) return;
            const matchedEntry = Object.entries(WORKSPACE_NAV_CONFIG).find(([, group]) => {
                return Object.entries(group.items || {}).some(([, item]) => {
                    return item.kind === 'subtab'
                        && (item.containerId || item.panelId || group.panelId) === containerId
                        && item.target === target;
                });
            });
            if (matchedEntry) {
                const [groupKey, group] = matchedEntry;
                const itemMatch = Object.entries(group.items || {}).find(([, item]) => {
                    return item.kind === 'subtab'
                        && (item.containerId || item.panelId || group.panelId) === containerId
                        && item.target === target;
                });
                if (itemMatch) {
                    activeWorkspaceNav = {group: groupKey, item: itemMatch[0]};
                    syncWorkspaceSidebarState(groupKey, itemMatch[0], {openActiveGroup: true});
                }
            }
            const nav = getDirectSubtabs(root);
            if (nav) {
                nav.querySelectorAll('.subtab-btn').forEach((node) => node.classList.toggle('active', node.dataset.target === target));
            }
            root.querySelectorAll('[data-subtab-group]').forEach((node) => {
                if (!(node instanceof HTMLElement)) return;
                const active = node.dataset.subtabGroup === target;
                if (!node.dataset.subtabDisplay) {
                    node.dataset.subtabDisplay = inferSubtabDisplay(node);
                }
                node.classList.toggle('active', active);
                node.style.display = active ? (node.dataset.subtabDisplay || inferSubtabDisplay(node)) : 'none';
            });
            root.querySelectorAll('.subtab-panel').forEach((node) => {
                const active = node.dataset.subtab === target;
                node.classList.toggle('active', active);
                node.style.display = active ? (node.dataset.subtabDisplay || inferSubtabDisplay(node)) : 'none';
            });
            if (containerId === 'panel-split') {
                updateSplitModeUI();
            }
        }

        function activateDefaultSecondaryTab(containerId) {
            const root = document.getElementById(containerId);
            if (!root) return;
            const nav = getDirectSubtabs(root);
            const first = nav?.querySelector('.subtab-btn');
            if (!first?.dataset?.target) return;
            activateSecondaryTab(containerId, first.dataset.target);
        }

        function activateHardSection(panelId, sectionId) {
            if (!panelId) return;
            const panel = document.getElementById(panelId);
            if (!panel) return;
            panel.querySelectorAll('.hard-section').forEach((node) => {
                node.style.display = node.id === sectionId ? '' : 'none';
            });
        }

        function showWorkspacePanel(panelId, focusId = '', options = {}) {
            const fallback = Object.entries(WORKSPACE_NAV_CONFIG).find(([, group]) => {
                if (group.panelId === panelId) return true;
                return Object.values(group.items || {}).some((item) => (item.panelId || group.panelId) === panelId);
            });
            if (!fallback) return;
            const fallbackGroupKey = fallback[0];
            const fallbackItemKey = Object.entries(fallback[1].items || {}).find(([, item]) => (item.panelId || fallback[1].panelId) === panelId)?.[0] || fallback[1].defaultItem;
            const mixTarget = focusId ? document.querySelector(`.sidebar-link[href="#${focusId}"]`)?.getAttribute('data-mix-target') : '';
            if (mixTarget) {
                applyWorkspaceNavigation(fallbackGroupKey, mixTarget, options);
                return;
            }
            applyWorkspaceNavigation(fallbackGroupKey, fallbackItemKey, options);
        }

        function initWorkspaceSidebar() {
            const links = Array.from(document.querySelectorAll('.sidebar-link[href^="#"]'));
            const toggles = Array.from(document.querySelectorAll('[data-group-toggle]'));
            if (!links.length) return;
            annotateWorkspaceSidebarLinks();

            toggles.forEach((toggle) => {
                toggle.addEventListener('click', () => {
                    const key = toggle.getAttribute('data-group-toggle');
                    const group = document.querySelector(`.sidebar-group[data-group="${key}"]`);
                    if (!group) return;
                    if (activeWorkspaceNav.group === key) {
                        group.classList.toggle('open');
                        return;
                    }
                    const config = getWorkspaceNavGroup(key);
                    if (config?.defaultItem) {
                        applyWorkspaceNavigation(key, config.defaultItem, {openActiveGroup: true});
                    }
                });
            });

            links.forEach((link) => {
                link.addEventListener('click', (event) => {
                    event.preventDefault();
                    const resolved = resolveWorkspaceNavFromLink(link);
                    if (!resolved) return;
                    applyWorkspaceNavigation(resolved.groupKey, resolved.itemKey, {openActiveGroup: true});
                });
            });
            activateHardSection('panel-account', 'account-profile-section');
            activateHardSection('panel-settings', 'settings-basic-section');
            applyWorkspaceNavigation('mix', 'group', {openActiveGroup: true, scroll: false});
        }

        function initSplitWorkspace() {
            const syncSplitMode = (event) => {
                if (event?.target?.id && event.target.id !== 'split_mode') return;
                updateSplitModeUI();
            };
            updateSplitModeUI();
            document.getElementById('split_mode')?.addEventListener('change', syncSplitMode);
            document.getElementById('split_mode')?.addEventListener('input', syncSplitMode);
            document.addEventListener('change', syncSplitMode);
            document.addEventListener('input', syncSplitMode);
        }

        function initEffectWorkspace() {
            initEffectInputs();
            loadResourceTypes();
            if (runtimeFeatures.duo) {
                loadDuoCategories();
                renderDuoLists();
                toggleDuoFields();
                loadDuoCacheStatus();
                loadFfmpegStatus();
                document.getElementById('duo_param_blur')?.addEventListener('change', syncDuoParamUI);
                document.getElementById('duo_param_shake')?.addEventListener('change', syncDuoParamUI);
                document.getElementById('duo_param_beauty')?.addEventListener('change', syncDuoParamUI);
            }
        }

        async function initWorkspacePage() {
            await loadSiteSettings();
            initTheme();
            initAuthUI();
            await loadRuntimeFeatures();
            await loadUserInfo();
            initWorkspaceSidebar();
            initDraftWorkspace();
            initEffectWorkspace();
            initSplitWorkspace();
            initSecondaryTabs('panel-split', [
                {id: 'split-file', label: '文件分割', indexes: [0]},
                {id: 'split-draft', label: '草稿处理', indexes: [1, 2]},
                {id: 'split-batch', label: '批量查看', indexes: [3]}
            ]);
            initSecondaryTabs('panel-effects', [
                {id: 'effects-core', label: '效果配置', indexes: [0, 4]},
                {id: 'effects-resource', label: '资源库', indexes: [1]},
                {id: 'effects-duo', label: 'Duo 资源', indexes: [2, 3, 5, 6]}
            ], {
                rootId: 'effects_section',
                getNodes(root) {
                    return Array.from(root.children).filter((node) => {
                        if (!(node instanceof HTMLElement)) return false;
                        if (node.classList.contains('quick-action-card')) return true;
                        if (node.classList.contains('tool-grid')) return true;
                        if (node.id === 'duoFeatureNotice' || node.id === 'duoSection') return true;
                        if (node.tagName === 'DETAILS') return true;
                        return false;
                    });
                }
            });
            initSecondaryTabs('clipToolsGrid', [
                {id: 'clip-ai', label: 'AI 灵感', indexes: [0]},
                {id: 'clip-rhythm', label: '节奏变速', indexes: [1]},
                {id: 'clip-transform', label: '画面校正', indexes: [2]},
                {id: 'clip-shake', label: '摇晃关键帧', indexes: [3]}
            ], {rootId: 'clipToolsGrid'});
            initSecondaryTabs('panel-export', [
                {id: 'export-settings', label: '导出设置', indexes: [0, 1]},
                {id: 'export-batch', label: '批量导出', indexes: [2]},
                {id: 'export-segments', label: '片段导出', indexes: [3]}
            ]);
            initSettingsWorkspace();
            await Promise.all([loadAiProviders(), loadAiKeys()]);
            initAiWorkspace();
            if (getWorkspaceSettings().auto_discover !== false) {
                discoverDrafts();
            }
            if (!getToken()) {
                openAuthModal();
                window.setTimeout(() => openAuthModal(), 120);
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            initWorkspacePage();
        });

        async function pollTaskStatus(jobId) {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(async () => {
                try {
                    const response = await authFetch(`/api/task/${jobId}`);
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.error || '查询失败');

                    const progress = data.progress || {};
                    let percent = 0;
                    if (typeof progress === 'number') {
                        percent = progress;
                    } else if (progress.progress) {
                        percent = parseFloat(progress.progress) || 0;
                    }
                    document.getElementById('progress-fill').style.width = `${percent}%`;
                    document.getElementById('progress-text').innerText = progress.indication || '处理中...';

                    if (data.status === 'finished') {
                        clearInterval(pollInterval);
                        pollInterval = null;
                        document.getElementById('progress-text').innerText = '✅ 生成完成！';
                        const summary = progress.effects_summary;
                        if (summary && summary.warnings && summary.warnings.length) {
                            const warnText = summary.warnings.map(w => `- ${w}`).join('<br>');
                            document.getElementById('progress-text').innerHTML += `<br>⚠️ 效果警告：<br>${warnText}`;
                        }
                        document.getElementById('submitBtn').disabled = false;
                        fetch('/api/drafts-folder')
                            .then(res => res.json())
                            .then(folderData => {
                                if (folderData.folder) {
                                    document.getElementById('progress-text').innerHTML += `<br>📂 草稿已保存至：${folderData.folder}`;
                                }
                            });
                    } else if (data.status === 'failed') {
                        clearInterval(pollInterval);
                        pollInterval = null;
                        document.getElementById('progress-text').innerText = `❌ 生成失败: ${data.error_msg || '未知错误'}`;
                        document.getElementById('submitBtn').disabled = false;
                    }
                } catch (error) {
                    document.getElementById('progress-text').innerText = `⚠️ 轮询出错: ${error.message}`;
                    clearInterval(pollInterval);
                    pollInterval = null;
                    document.getElementById('submitBtn').disabled = false;
                }
            }, 2000);
        }
    

let aiProviders = [];
let aiKeys = [];
let editingAiKeyId = null;
let mangaCharacterBase64 = '';
let mangaAbortController = null;
let mangaProgressTimer = null;
let mangaTemplatesCache = [];
let mangaHistoryCache = [];
let aiRecentMaterialsCache = [];
let notifyTimer = null;

function notify(message, level = 'info') {
    const box = document.getElementById('globalToast');
    if (!box) return;
    box.textContent = message || '';
    box.dataset.level = level;
    box.classList.add('visible');
    if (notifyTimer) window.clearTimeout(notifyTimer);
    notifyTimer = window.setTimeout(() => {
        box.classList.remove('visible');
    }, 2600);
}

function setInlineMessage(element, message, level = 'info') {
    if (!element) return;
    element.textContent = message || '';
    element.dataset.level = level;
}

async function confirmAction(message) {
    return window.confirm(message || '确认执行此操作吗？');
}

function mapAiKeyOptions(selectId, providerCode) {
    const el = document.getElementById(selectId);
    if (!el) return;
    const items = aiKeys.filter((item) => item.provider_code === providerCode && item.is_active !== false);
    el.innerHTML = items.length ? items.map((item) => `<option value="${item.id}">${item.key_name}</option>`).join('') : '<option value="">请选择</option>';
}

function renderAiKeysList() {
    const box = document.getElementById('ai_keys_list');
    if (!box) return;
    if (!aiKeys.length) {
        box.innerHTML = '还没有保存账号。先选择服务，填写账号名称和密钥后再保存。';
        return;
    }
    box.innerHTML = aiKeys.map((item) => `
        <div class="key-item">
            <div class="key-row"><strong>${item.key_name}</strong><span class="key-badge">${item.provider_name || item.provider_code}</span></div>
            <div class="key-row"><span>${item.masked_key || '-'}</span><span>${item.is_active ? '启用' : '停用'}</span></div>
            <div class="key-actions"><button class="effect-add" type="button" onclick="editAiKey(${item.id})">编辑</button><button class="effect-add" type="button" onclick="testAiKey(${item.id})">测试</button><button class="effect-add" type="button" onclick="toggleAiKeyActive(${item.id}, ${item.is_active ? 'false' : 'true'})">${item.is_active ? '停用' : '启用'}</button><button class="effect-add" type="button" onclick="deleteAiKey(${item.id})">删除</button></div>
        </div>
    `).join('');
}

function renderProviderList() {
    const list = document.getElementById('ai_provider_list');
    const select = document.getElementById('ai_provider_select');
    if (select) {
        select.innerHTML = aiProviders.length ? aiProviders.map((item) => `<option value="${item.id}">${item.provider_name}</option>`).join('') : '<option value="">暂无可用服务</option>';
    }
    if (!list) return;
    if (!aiProviders.length) {
        list.textContent = '暂时还没有可用服务。请检查初始化数据或重新登录后再试。';
        return;
    }
    list.innerHTML = aiProviders.map((item) => `<div class="key-item"><div class="key-row"><strong>${item.provider_name}</strong><span class="key-badge">${item.provider_code}</span></div><div class="key-row"><span>${item.description || ''}</span></div></div>`).join('');
}

function setAiAccountMessage(message, level = 'info') {
    const box = document.getElementById('ai_key_tip');
    if (!box) return;
    box.style.color = level === 'error' ? '#ef4444' : level === 'warn' ? '#d97706' : '#64748b';
    box.textContent = message || '不同服务填写项略有区别，不确定时先看说明。';
}

function updateAiProviderGuideHint() {
    const providerId = document.getElementById('ai_provider_select')?.value;
    const provider = aiProviders.find((item) => String(item.id) === String(providerId));
    const apiKeyInput = document.getElementById('ai_api_key');
    const secretInput = document.getElementById('ai_api_secret');
    const endpointInput = document.getElementById('ai_endpoint');
    const baseUrlInput = document.getElementById('ai_base_url');
    const guide = document.getElementById('ai_provider_guide');
    if (guide) {
        guide.style.display = 'none';
        guide.textContent = '';
    }
    if (!provider) {
        if (apiKeyInput) apiKeyInput.placeholder = '';
        if (secretInput) secretInput.placeholder = '';
        if (endpointInput) endpointInput.placeholder = '';
        if (baseUrlInput) baseUrlInput.placeholder = '例如 https://api.openai.com/v1';
        setAiAccountMessage('先选择一个服务，再填写账号信息。', 'warn');
        return;
    }
    if (provider.provider_code === 'jimeng') {
        if (apiKeyInput) apiKeyInput.placeholder = '填写 Access Key';
        if (secretInput) secretInput.placeholder = '填写 Secret Key';
        if (endpointInput) endpointInput.placeholder = '填写接入域名或地域标识';
        if (baseUrlInput) baseUrlInput.placeholder = '通常可留空';
        setAiAccountMessage('即梦一般需要 AK、SK、Endpoint 三项。测试账号时还要提供 Action 和 Version。');
        return;
    }
    if (provider.provider_code === 'volc') {
        if (apiKeyInput) apiKeyInput.placeholder = '填写 access_token';
        if (secretInput) secretInput.placeholder = '填写 appid';
        if (endpointInput) endpointInput.placeholder = '填写 cluster';
        if (baseUrlInput) baseUrlInput.placeholder = '通常可留空';
        setAiAccountMessage('火山 TTS 一般需要 access_token、appid、cluster。测试账号时会额外使用音色。');
        return;
    }
    if (apiKeyInput) apiKeyInput.placeholder = '填写 API Key';
    if (secretInput) secretInput.placeholder = '按需填写补充密钥';
    if (endpointInput) endpointInput.placeholder = '按需填写模型或通道';
    if (baseUrlInput) baseUrlInput.placeholder = '例如 https://api.openai.com/v1';
    setAiAccountMessage('OpenAI 兼容服务通常需要账号名称、API Key 和服务地址。');
}

async function loadAiProviders() {
    if (!getToken()) {
        aiProviders = [];
        renderProviderList();
        setAiAccountMessage('请先登录后再管理 AI 账号。', 'warn');
        return;
    }
    try {
        const res = await authFetch('/api/ai/providers');
        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.error || '加载失败');
        aiProviders = Array.isArray(data.items) ? data.items : [];
    } catch (e) {
        aiProviders = [];
        setAiAccountMessage(`AI 服务列表加载失败：${e.message || e}`, 'error');
    }
    renderProviderList();
    updateAiProviderGuideHint();
}

async function loadAiKeys() {
    if (!getToken()) {
        aiKeys = [];
        renderAiKeysList();
        renderAiPromptKeyOptions([]);
        mapAiKeyOptions('ai_jimeng_key', 'jimeng');
        mapAiKeyOptions('ai_volc_key', 'volc');
        mapAiKeyOptions('ai_openai_key', 'openai');
        setAiAccountMessage('请先登录后再读取 AI 账号。', 'warn');
        return;
    }
    try {
        const res = await authFetch('/api/user/keys');
        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.error || '加载失败');
        aiKeys = Array.isArray(data.items) ? data.items : [];
    } catch (e) {
        aiKeys = [];
        const box = document.getElementById('ai_keys_list');
        if (box) box.textContent = `账号列表加载失败：${e.message || e}`;
    }
    renderAiKeysList();
    renderAiPromptKeyOptions(aiKeys);
    mapAiKeyOptions('ai_jimeng_key', 'jimeng');
    mapAiKeyOptions('ai_volc_key', 'volc');
    mapAiKeyOptions('ai_openai_key', 'openai');
}

function resetAiKeyForm() {
    editingAiKeyId = null;
    ['ai_key_name', 'ai_api_key', 'ai_api_secret', 'ai_endpoint', 'ai_base_url'].forEach((id) => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    updateAiProviderGuideHint();
}

function editAiKey(id) {
    const item = aiKeys.find((entry) => String(entry.id) === String(id));
    if (!item) return;
    editingAiKeyId = item.id;
    if (document.getElementById('ai_provider_select')) document.getElementById('ai_provider_select').value = item.provider_id;
    if (document.getElementById('ai_key_name')) document.getElementById('ai_key_name').value = item.key_name || '';
    if (document.getElementById('ai_endpoint')) document.getElementById('ai_endpoint').value = item.endpoint || '';
    if (document.getElementById('ai_base_url')) document.getElementById('ai_base_url').value = item.base_url || '';
    updateAiProviderGuideHint();
    setAiAccountMessage(`正在编辑账号：${item.key_name}`);
}

async function saveAiKey() {
    const providerId = document.getElementById('ai_provider_select')?.value;
    const provider = aiProviders.find((item) => String(item.id) === String(providerId));
    const payload = {
        provider_code: provider ? provider.provider_code : undefined,
        key_name: document.getElementById('ai_key_name')?.value?.trim() || '',
        api_key: document.getElementById('ai_api_key')?.value?.trim() || '',
        api_secret: document.getElementById('ai_api_secret')?.value?.trim() || '',
        endpoint: document.getElementById('ai_endpoint')?.value?.trim() || '',
        base_url: document.getElementById('ai_base_url')?.value?.trim() || ''
    };
    if (!payload.provider_code || !payload.key_name || (!payload.api_key && !editingAiKeyId)) {
        setAiAccountMessage('请填写服务、账号名称和访问密钥。编辑已有账号时，主密钥可留空表示不改。', 'warn');
        notify('请填写服务、账号名称和访问密钥', 'warn');
        return;
    }
    const url = editingAiKeyId ? `/api/user/keys/${editingAiKeyId}` : '/api/user/keys';
    const method = editingAiKeyId ? 'PUT' : 'POST';
    const res = await authFetch(url, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        setAiAccountMessage(data.error || '保存失败，请检查填写项是否完整。', 'error');
        notify(data.error || '保存失败', 'error');
        return;
    }
    const message = editingAiKeyId ? '账号已更新。' : '账号已保存。';
    resetAiKeyForm();
    await loadAiKeys();
    setAiAccountMessage(message);
    notify(message.replace('。', ''), 'success');
}

async function deleteAiKey(id) {
    if (!await confirmAction('确认删除这个 AI 账号吗？')) return;
    const res = await authFetch(`/api/user/keys/${id}`, { method: 'DELETE' });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        notify(data.error || '删除失败', 'error');
        return;
    }
    await loadAiKeys();
    notify('AI 账号已删除', 'success');
}

async function toggleAiKeyActive(id, flag) {
    const res = await authFetch(`/api/user/keys/${id}`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ is_active: !!flag }) });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        notify(data.error || '更新失败', 'error');
        return;
    }
    await loadAiKeys();
    notify(flag ? 'AI 账号已启用' : 'AI 账号已停用', 'success');
}

async function testAiKey(id) {
    const item = aiKeys.find((entry) => String(entry.id) === String(id));
    const payload = {};
    if (item?.provider_code === 'volc') {
        payload.voice_type = document.getElementById('ai_volc_voice')?.value || 'BV001';
        payload.text = '测试语音';
    }
    if (item?.provider_code === 'jimeng') {
        payload.action = document.getElementById('ai_jimeng_action')?.value?.trim() || '';
        payload.version = document.getElementById('ai_jimeng_version')?.value?.trim() || '';
        if (!payload.action || !payload.version) {
            setAiAccountMessage('测试即梦账号前，请先在 AI 成片里补齐 Action 和 Version。', 'warn');
            notify('请先补齐即梦的 Action 和 Version', 'warn');
            return;
        }
    }
    const res = await authFetch(`/api/user/keys/${id}/test`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    const data = await res.json();
    setAiAccountMessage(data.ok ? '账号测试通过。' : (data.error || data.message || '账号测试失败，请检查服务参数。'), data.ok ? 'info' : 'error');
    notify(data.ok ? '测试通过' : (data.error || data.message || '测试失败'), data.ok ? 'success' : 'error');
}

async function showProviderGuide() {
    const providerId = document.getElementById('ai_provider_select')?.value;
    const provider = aiProviders.find((item) => String(item.id) === String(providerId));
    const box = document.getElementById('ai_provider_guide');
    if (!provider || !box) return;
    const res = await authFetch(`/api/ai/providers/${provider.provider_code}/guide`);
    const data = await res.json();
    box.style.display = 'block';
    box.textContent = data.content || '暂无说明';
}

async function pollAiTask(taskId, statusId, resultId = '') {
    const statusEl = typeof statusId === 'string' ? document.getElementById(statusId) : statusId;
    const resultEl = resultId ? document.getElementById(resultId) : null;
    let count = 0;
    const timer = setInterval(async () => {
        count += 1;
        if (count > 120) {
            clearInterval(timer);
            if (statusEl) statusEl.textContent = '任务超时';
            return;
        }
        try {
            const res = await authFetch(`/api/ai/task/${taskId}`);
            const data = await res.json();
            if (!res.ok || data.ok === false) throw new Error(data.error || '查询失败');
            const task = data.task || {};
            if (task.status === 'success') {
                clearInterval(timer);
                if (statusEl) statusEl.textContent = '生成完成';
                if (resultEl) resultEl.value = task.result_text || task.result || '';
                await refreshAiMaterials();
                await loadMangaHistory();
                return;
            }
            if (task.status === 'failed') {
                clearInterval(timer);
                if (statusEl) statusEl.textContent = task.error_msg || '执行失败';
            }
        } catch (e) {
            clearInterval(timer);
            if (statusEl) statusEl.textContent = e.message || '查询失败';
        }
    }, 2000);
}

async function startAiVideo() {
    const payload = {
        key_id: parseInt(document.getElementById('ai_jimeng_key')?.value || '0', 10),
        prompt: document.getElementById('ai_jimeng_prompt')?.value?.trim() || '',
        style: document.getElementById('ai_jimeng_style')?.value || '',
        extra_body: {
            action: document.getElementById('ai_jimeng_action')?.value?.trim() || '',
            version: document.getElementById('ai_jimeng_version')?.value?.trim() || ''
        }
    };
    if (!payload.key_id || !payload.prompt) {
        document.getElementById('ai_jimeng_status').textContent = '请先选择账号并填写提示词';
        return;
    }
    document.getElementById('ai_jimeng_status').textContent = '正在提交，请稍候...';
    const res = await authFetch('/api/ai/generate/video', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        document.getElementById('ai_jimeng_status').textContent = data.error || '提交失败';
        return;
    }
    pollAiTask(data.task_id, 'ai_jimeng_status');
}

async function startAiAudio() {
    const payload = {
        key_id: parseInt(document.getElementById('ai_volc_key')?.value || '0', 10),
        text: document.getElementById('ai_volc_text')?.value?.trim() || '',
        voice_type: document.getElementById('ai_volc_voice')?.value || ''
    };
    if (!payload.key_id || !payload.text || !payload.voice_type) {
        document.getElementById('ai_volc_status').textContent = '请先把参数填写完整';
        return;
    }
    document.getElementById('ai_volc_status').textContent = '正在提交，请稍候...';
    const res = await authFetch('/api/ai/generate/audio', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        document.getElementById('ai_volc_status').textContent = data.error || '提交失败';
        return;
    }
    pollAiTask(data.task_id, 'ai_volc_status');
}

async function startAiText() {
    const payload = {
        key_id: parseInt(document.getElementById('ai_openai_key')?.value || '0', 10),
        prompt: `${document.getElementById('ai_text_prompt')?.value?.trim() || ''}\n\n字数:${document.getElementById('ai_text_length')?.value || '50'}`
    };
    if (!payload.key_id || !payload.prompt.trim()) {
        document.getElementById('ai_text_status').textContent = '请先把参数填写完整';
        return;
    }
    document.getElementById('ai_text_status').textContent = '正在提交，请稍候...';
    const res = await authFetch('/api/ai/generate/text', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        document.getElementById('ai_text_status').textContent = data.error || '提交失败';
        return;
    }
    pollAiTask(data.task_id, 'ai_text_status', 'ai_text_result');
}

function fillTextPanelFromAi() {
    const text = document.getElementById('ai_text_result')?.value?.trim();
    if (!text) return;
    const firstInput = document.querySelector('#texts_area input[type="text"]');
    if (firstInput) firstInput.value = text;
}

async function refreshAiMaterials() {
    const box = document.getElementById('ai_recent_materials');
    if (!box || !getToken()) return;
    const res = await authFetch('/api/user/materials');
    const data = await res.json();
    aiRecentMaterialsCache = Array.isArray(data.items) ? data.items.slice(0, 20) : [];
    box.innerHTML = aiRecentMaterialsCache.length ? aiRecentMaterialsCache.map((item) => {
        const materialId = item.id || '';
        const checked = item.source === 'openclaw' || String(item.file_path || '').toLowerCase().includes('manga');
        return `<div class="key-item">
            <div class="key-row"><strong>${item.file_type || '-'}</strong><span class="key-badge">${item.source || '-'}</span></div>
            <div class="key-row"><span>编号：${materialId || '-'}</span><label><input type="checkbox" class="manga-material-check" value="${materialId}" ${checked ? 'checked' : ''}> 选中</label></div>
            <div class="key-row"><span>${item.file_path || '-'}</span></div>
        </div>`;
    }).join('') : '这里会显示最近生成的素材。';
}

function getSelectedMangaMaterialIds() {
    const fromChecks = Array.from(document.querySelectorAll('.manga-material-check:checked'))
        .map((item) => parseInt(item.value || '0', 10))
        .filter((id) => !Number.isNaN(id) && id > 0);
    if (fromChecks.length) return fromChecks;
    const raw = document.getElementById('manga_batch_ids')?.value || '';
    return raw.split(',').map((item) => parseInt(item.trim(), 10)).filter((id) => !Number.isNaN(id) && id > 0);
}

function fillMangaBatchSelection() {
    const ids = getSelectedMangaMaterialIds();
    const input = document.getElementById('manga_batch_ids');
    if (input) input.value = ids.join(', ');
}

function setMangaBatchStatus(message) {
    const box = document.getElementById('manga_batch_status');
    if (box) box.textContent = message || '';
}

async function applyMangaBatchDuration() {
    const material_ids = getSelectedMangaMaterialIds();
    const duration = parseFloat(document.getElementById('manga_batch_duration')?.value || '3');
    if (!material_ids.length) {
        setMangaBatchStatus('请先选择要处理的 AI 素材。');
        return;
    }
    const res = await authFetch('/api/manga/batch/set-duration', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({material_ids, duration})
    });
    const data = await res.json();
    setMangaBatchStatus(data.ok ? `已更新 ${data.updated || 0} 个素材时长。` : (data.error || '批量设时长失败'));
}

async function applyMangaBatchEffects() {
    const material_ids = getSelectedMangaMaterialIds();
    const raw = document.getElementById('manga_batch_effects')?.value?.trim() || '';
    if (!material_ids.length) {
        setMangaBatchStatus('请先选择要处理的 AI 素材。');
        return;
    }
    let effects = {};
    if (raw) {
        try {
            effects = JSON.parse(raw);
        } catch (e) {
            setMangaBatchStatus('效果设置格式不正确。');
            return;
        }
    }
    const res = await authFetch('/api/manga/batch/apply-effects', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({material_ids, effects})
    });
    const data = await res.json();
    setMangaBatchStatus(data.ok ? `已更新 ${data.updated || 0} 个素材效果参数。` : (data.error || '批量加效果失败'));
}

async function exportMangaBatch() {
    const material_ids = getSelectedMangaMaterialIds();
    const duration = parseFloat(document.getElementById('manga_batch_duration')?.value || '3');
    if (!material_ids.length) {
        setMangaBatchStatus('请先选择要导出的 AI 素材。');
        return;
    }
    setMangaBatchStatus('正在批量导出 AI 漫剧素材...');
    const res = await authFetch('/api/manga/batch/export', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({material_ids, duration})
    });
    const data = await res.json();
    setMangaBatchStatus(data.ok ? `批量导出完成，新增 ${data.added || 0} 个视频素材。` : (data.error || '批量导出失败'));
    if (data.ok) {
        await refreshAiMaterials();
        await loadUserMaterials();
    }
}

function openOpenclawConfig() {
    openWorkspaceSettingsSection('settings-service-section');
}

function closeOpenclawConfig() {
    const modal = document.getElementById('openclawModal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
}

async function loadOpenclawConfig() {
    try {
        const settings = await loadWorkspaceSettingsConfig();
        const config = (settings.services || {}).openclaw || {};
        if (document.getElementById('settingsOpenclawBaseUrl')) document.getElementById('settingsOpenclawBaseUrl').value = config.base_url || 'http://localhost:18789';
        if (document.getElementById('settingsOpenclawToken')) document.getElementById('settingsOpenclawToken').value = config.token || '';
    } catch (e) {}
}

async function saveOpenclawConfig() {
    const base_url = document.getElementById('settingsOpenclawBaseUrl')?.value?.trim() || '';
    const token = document.getElementById('settingsOpenclawToken')?.value?.trim() || '';
    try {
        await saveWorkspaceSettingsConfig({services: {openclaw: {base_url, token}}});
        const statusEl = document.getElementById('openclawSettingsStatus');
        if (statusEl) statusEl.textContent = 'AI 漫剧服务已保存';
    } catch (e) {
        const statusEl = document.getElementById('openclawSettingsStatus');
        if (statusEl) statusEl.textContent = `保存失败：${e.message || e}`;
    }
}

async function testOpenclawConfig() {
    const base_url = document.getElementById('settingsOpenclawBaseUrl')?.value?.trim() || '';
    const token = document.getElementById('settingsOpenclawToken')?.value?.trim() || '';
    const res = await authFetch('/api/openclaw/test', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ base_url, token }) });
    const data = await res.json();
    const statusEl = document.getElementById('openclawSettingsStatus');
    if (statusEl) statusEl.textContent = data.ok ? 'AI 漫剧服务连接成功' : (data.error || '连接失败');
}

function collectShotTypes() {
    return Array.from(document.querySelectorAll('#manga_shot_types input[type="checkbox"]')).filter((item) => item.checked).map((item) => item.value);
}

function setMangaStatus(message) {
    const el = document.getElementById('manga_status');
    if (el) el.textContent = message || '';
}

function setMangaProgress(value) {
    const el = document.getElementById('manga_progress_fill');
    if (el) el.style.width = `${Math.max(0, Math.min(100, value))}%`;
}

function startMangaProgress() {
    clearInterval(mangaProgressTimer);
    let value = 8;
    setMangaProgress(value);
    mangaProgressTimer = setInterval(() => {
        value = Math.min(85, value + Math.random() * 4);
        setMangaProgress(value);
    }, 600);
}

function stopMangaProgress() {
    clearInterval(mangaProgressTimer);
    setMangaProgress(0);
}

function setMangaUiRunning(running) {
    const btn = document.getElementById('manga_generate_btn');
    const cancelBtn = document.getElementById('manga_cancel_btn');
    if (btn) btn.disabled = running;
    if (cancelBtn) cancelBtn.style.display = running ? 'inline-flex' : 'none';
}

async function startMangaGenerate() {
    if (!getToken()) {
        setMangaStatus('请先登录');
        return;
    }
    if (!runtimeFeatures.manga) {
        setMangaStatus(`当前未开启 AI 漫剧，需要 ${getRuntimeRequirementText('manga')}`);
        return;
    }
    const script = document.getElementById('manga_script')?.value?.trim() || '';
    if (!script) {
        setMangaStatus('请先填写分镜脚本');
        return;
    }
    try {
        const settings = await loadWorkspaceSettingsConfig();
        const service = (settings.services || {}).openclaw || {};
        if (!service.base_url) {
            setMangaStatus('请先到“软件设置 -> AI 漫剧服务”填写服务地址');
            openWorkspaceSettingsSection('settings-service-section');
            return;
        }
    } catch (e) {
        setMangaStatus(`读取 AI 漫剧服务失败：${e.message || e}`);
        return;
    }
    setMangaUiRunning(true);
    setMangaStatus('生成中...');
    startMangaProgress();
    mangaAbortController = new AbortController();
    const payload = {
        character_image: mangaCharacterBase64 || '',
        script,
        style: document.getElementById('manga_style')?.value || '',
        shot_types: collectShotTypes(),
        frame_count: parseInt(document.getElementById('manga_frame_count')?.value || '5', 10),
        image_resolution: document.getElementById('manga_image_resolution')?.value || '768x768',
        video_bitrate: parseInt(document.getElementById('manga_video_bitrate')?.value || '2000', 10)
    };
    try {
        const res = await authFetch('/api/ai/manga/generate', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: mangaAbortController.signal });
        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.error || '生成失败');
        renderMangaResult(data.frames || [], data.video || null);
        setMangaStatus(data.message || '生成完成');
        await refreshAiMaterials();
        await loadMangaHistory();
    } catch (e) {
        setMangaStatus(e.message || '生成失败');
    } finally {
        setMangaUiRunning(false);
        stopMangaProgress();
    }
}

function cancelMangaGenerate() {
    if (mangaAbortController) mangaAbortController.abort();
    setMangaUiRunning(false);
    stopMangaProgress();
    setMangaStatus('已取消');
}

function renderMangaResult(frames, video) {
    const frameBox = document.getElementById('manga_result_frames');
    const videoBox = document.getElementById('manga_result_video');
    const token = getToken();
    const withToken = (url) => url ? `${url}?token=${encodeURIComponent(token)}` : '';
    if (videoBox) videoBox.innerHTML = video ? `<video class="manga-video" src="${withToken(video.preview_url)}" controls></video>` : '<div class="hint">暂无视频</div>';
    if (frameBox) frameBox.innerHTML = Array.isArray(frames) && frames.length ? frames.map((item) => `<div class="manga-thumb"><img src="${withToken(item.preview_url)}" alt="frame"></div>`).join('') : '<div class="hint">暂无帧图</div>';
}

async function loadMangaTemplates() {
    const box = document.getElementById('manga_template_list');
    if (!box || !getToken()) return;
    const res = await authFetch('/api/manga/templates');
    const data = await res.json();
    mangaTemplatesCache = Array.isArray(data.items) ? data.items : [];
    box.innerHTML = mangaTemplatesCache.length ? mangaTemplatesCache.map((item) => `<div class="key-item"><div class="key-row"><strong>${item.name}</strong><span class="key-badge">${item.usage_count || 0}</span></div><div class="key-actions"><button class="effect-add" type="button" onclick="applyMangaTemplate(${item.id}, false)">填充</button><button class="effect-add" type="button" onclick="applyMangaTemplate(${item.id}, true)">直接生成</button></div></div>`).join('') : '暂无模板';
}

async function saveMangaTemplate() {
    const name = document.getElementById('manga_template_name')?.value?.trim() || '';
    if (!name) {
        setMangaStatus('请先填写预设名称');
        return;
    }
    const payload = {
        name,
        params: {
            script: document.getElementById('manga_script')?.value?.trim() || '',
            style: document.getElementById('manga_style')?.value || '',
            shot_types: collectShotTypes(),
            frame_count: parseInt(document.getElementById('manga_frame_count')?.value || '5', 10),
            image_resolution: document.getElementById('manga_image_resolution')?.value || '768x768',
            video_bitrate: parseInt(document.getElementById('manga_video_bitrate')?.value || '2000', 10)
        }
    };
    const res = await authFetch('/api/manga/templates', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        setMangaStatus(data.error || '保存模板失败');
        return;
    }
    document.getElementById('manga_template_name').value = '';
    await loadMangaTemplates();
    setMangaStatus('模板已保存');
}

async function applyMangaTemplate(templateId, autoRun) {
    const res = await authFetch(`/api/manga/templates/${templateId}/use`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.ok === false) return;
    const params = data.params || {};
    if (document.getElementById('manga_script')) document.getElementById('manga_script').value = params.script || '';
    if (document.getElementById('manga_style') && params.style) document.getElementById('manga_style').value = params.style;
    if (document.getElementById('manga_frame_count') && params.frame_count) document.getElementById('manga_frame_count').value = params.frame_count;
    if (document.getElementById('manga_image_resolution') && params.image_resolution) document.getElementById('manga_image_resolution').value = params.image_resolution;
    if (document.getElementById('manga_video_bitrate') && params.video_bitrate) document.getElementById('manga_video_bitrate').value = params.video_bitrate;
    if (autoRun) startMangaGenerate();
}

async function loadMangaHistory() {
    const box = document.getElementById('manga_history_list');
    if (!box || !getToken()) return;
    const res = await authFetch('/api/manga/history');
    const data = await res.json();
    mangaHistoryCache = Array.isArray(data.items) ? data.items : [];
    box.innerHTML = mangaHistoryCache.length ? mangaHistoryCache.map((item) => `<div class="key-item"><div class="key-row"><strong>${item.project_name || item.project_id || '历史记录'}</strong><span class="key-badge">${item.created_at || '-'}</span></div><div class="key-actions"><button class="effect-add" type="button" onclick="regenerateFromHistory(${item.id})">重新生成</button><button class="effect-add" type="button" onclick="redownloadFromHistory(${item.id})">重新下载</button></div></div>`).join('') : '暂无历史';
}

async function regenerateFromHistory(id) {
    const res = await authFetch(`/api/manga/history/${id}/regenerate`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        setMangaStatus(data.error || '重新生成失败');
        return;
    }
    renderMangaResult(data.frames || [], data.video || null);
    setMangaStatus(data.message || '已重新生成');
}

async function redownloadFromHistory(id) {
    const res = await authFetch(`/api/manga/history/${id}/redownload`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        setMangaStatus(data.error || '重新下载失败');
        return;
    }
    renderMangaResult(data.frames || [], data.video || null);
    setMangaStatus(data.message || '已重新下载');
}

async function openOpenclawLogModal() {
    const modal = document.getElementById('openclawLogModal');
    if (!modal) return;
    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');
    const res = await authFetch('/api/openclaw/logs?limit=200');
    const data = await res.json();
    if (document.getElementById('openclaw_log_path')) document.getElementById('openclaw_log_path').textContent = data.path || '';
    if (document.getElementById('openclaw_log_content')) document.getElementById('openclaw_log_content').textContent = data.content || '';
}

function closeOpenclawLogModal() {
    const modal = document.getElementById('openclawLogModal');
    if (!modal) return;
    modal.classList.remove('open');
    modal.setAttribute('aria-hidden', 'true');
}

async function copyOpenclawLogPath() {
    const text = document.getElementById('openclaw_log_path')?.textContent || '';
    if (!text) return;
    await navigator.clipboard.writeText(text);
}

function buildMangaShotTypes() {
    const box = document.getElementById('manga_shot_types');
    if (!box || box.children.length) return;
    const shots = ['特写', '近景', '中景', '远景', '推镜', '摇镜'];
    box.innerHTML = shots.map((item, index) => `<label><input type="checkbox" value="${item}" ${index < 2 ? 'checked' : ''}> ${item}</label>`).join(' ');
}

function initAiWorkspace() {
    refreshAiMaterials();
    document.getElementById('ai_provider_select')?.addEventListener('change', updateAiProviderGuideHint);
    if (runtimeFeatures.manga) {
        loadMangaTemplates();
        loadMangaHistory();
        buildMangaShotTypes();
    }
    const mangaFile = document.getElementById('manga_character_file');
    if (mangaFile && !mangaFile.dataset.bound) {
        mangaFile.dataset.bound = 'true';
        mangaFile.addEventListener('change', async (event) => {
            const file = event.target.files && event.target.files[0];
            if (!file) return;
            const reader = new FileReader();
            reader.onload = () => {
                mangaCharacterBase64 = reader.result || '';
                const img = document.getElementById('manga_character_preview');
                if (img) img.src = mangaCharacterBase64;
            };
            reader.readAsDataURL(file);
        });
    }
}
