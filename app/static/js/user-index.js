        let currentDraftPath = '';
        let currentDraftInfoPath = '';
        let materialsConfig = [];
        let materialSlotMeta = [];
        let currentMaterialLayout = null;
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
            manga: ['MANGA_FEATURES_ENABLED']
        };
        let currentUserInfo = null;
        let accountOverview = null;
        let activeDraftShell = null;
        let assistantPreviewState = null;
        let storyboardItemsCache = [];
        let storyboardSourceTextCache = '';
        let resourceExchangeState = {
            page: 1,
            pages: 1,
            total: 0,
            items: [],
            myPosts: []
        };
        const EFFECT_TYPE_LABELS = {
            VIDEO_SCENE: '视频场景',
            ToneEffectType: '色调效果',
            AudioSceneEffectType: '音频效果',
            filter_type: '滤镜',
            SpeechToSongType: '语音转歌曲',
            mask_type: '蒙版',
            TransitionType: '转场',
            Font: '字体',
            TextIntro: '文字入场',
            TextOutro: '文字退场',
            TextLoopAnim: '文字循环动画',
            GroupAnimationType: '组合动画',
            VIDEO_CHARACTER: '人物特效',
            IntroType: '片头',
            OutroType: '片尾'
        };
        const DUO_CATEGORY_LABELS = {
            video_effects: '视频特效',
            transitions: '转场',
            face_effects: '人像优化',
            stickers: '贴纸',
            text_templates: '文字模板'
        };

        const ACCOUNT_TUTORIAL_ENTRIES = [
            {title: '智能助手', keywords: '智能助手 命令中心 创建素材目录 分区 混剪 导出 草稿', body: '直接输入一句需求，助手会先告诉你准备执行什么，再决定是否继续。适合快速创建素材目录、跳转到指定混剪模式，或者导出当前草稿。'},
            {title: '批量混剪', keywords: '批量混剪 按组精准替换 混剪裂变替换 分区混剪裂变 槽位拼接混剪', body: '先选参考草稿，再按当前模式准备素材目录或文字内容。前三种模式会保持每次每槽位使用 1 个素材，槽位拼接混剪则会在单个槽位内连续拼接多段视频。'},
            {title: 'AI 成片', keywords: 'AI 成片 即梦 火山 TTS AI 文案 AI账号管理', body: '先在“软件设置 -> AI账号管理”里维护好账号，再回到本页执行图生视频、语音合成或文案生成。页面里只保留真正会影响出片的参数。'},
            {title: 'AI 漫剧', keywords: 'AI 漫剧 草稿 分镜 脚本 场景目录', body: 'AI 漫剧会直接生成剪映草稿、场景素材目录和分镜说明。你可以先拿到完整草稿结构，再按自己的节奏补图、补视频和细化镜头。'},
            {title: '漫剧助手', keywords: '漫剧助手 SRT 分镜 生图 文案转SRT', body: '这条链路只做“文案整理成 SRT 分镜”和“按句生图”，不会改官方草稿。建议先在这里把对白、人物和画面提示词整理顺，再去做正式草稿。'},
            {title: '批量效果', keywords: '批量效果 Duo 资源 贴纸 转场', body: '选好草稿后，可以直接搜索你想要的效果或素材，再一键加入当前草稿。日常先用分类、关键词和常用预设就够了，不需要一开始就碰高级参数。'},
            {title: '批量分割', keywords: '批量分割 文件分割 草稿处理 批量查看', body: '既可以对文件按时长、镜头或字幕做分割，也可以批量查看草稿结构，提前排查内容问题，再决定是否导出或继续加工。'},
            {title: '片段微调', keywords: '片段微调 节奏变速 画面校正 摇晃关键帧', body: '适合在出片前做最后一轮细节调整，例如节奏变速、画面校正、镜像、摇晃关键帧和局部修饰。'},
            {title: '批量导出', keywords: '批量导出 导出设置 多草稿 片段导出', body: '把当前草稿或多份草稿加入队列后，可以统一导出；也支持单独导出主要视频片段，方便复用和复检。'},
            {title: '账户中心', keywords: '账户中心 账户信息 VIP说明 邀请中心 授权激活 使用教程', body: '这里集中查看会员状态、剩余次数、签到奖励、邀请关系、授权激活和全站使用教程，生成前也会同步刷新当前余额。'},
            {title: '资源互换', keywords: '资源互换 资源大厅 互换发布 审核 免费', body: '资源互换是免费功能，不扣次数。你可以先在资源大厅找合作和置换信息，再到互换发布里提交自己的项目，并随时查看审核状态和发布时间。'},
            {title: '软件设置', keywords: '软件设置 工作台设置 路径与目录 AI账号管理', body: '工作台偏好、默认目录和 AI 账号都统一放在这里维护。日常使用时先把常用路径和账号配好，后续每个功能页都会直接复用。'}
        ];

        const tokenKey = 'vf_token';
        const themeKey = 'vf_theme';
        const workspaceSettingsKey = 'vf_workspace_settings';
        const recentMaterialFoldersKey = 'vf_recent_material_folders';
        const rememberedLoginKey = 'vf_remembered_login';
        const runtimeUserTokenStateKey = 'user_session_token';
        const runtimeUserPersistStateKey = 'user_session_persist';
        const workspaceSensitiveSettingKeys = ['net_provider', 'net_base_url', 'net_token'];
        let workspaceSettingsConfigCache = null;
        let siteSettingsCache = readInitialSiteSettings();
        const announcementDismissKey = 'vf_announcement_dismissed_today';
        let announcementState = {
            items: [],
            index: 0,
            sessionShownKey: ''
        };
        let licenseCardTypesRequestSeq = 0;

        function inferMaterialTypeFromLabel(label = '') {
            const raw = String(label || '').trim().toLowerCase();
            if (!raw) return '';
            if (/(音频|音乐|配乐|旁白|bgm|audio|voice|sound)/.test(raw)) return 'audio';
            if (/(图片|图像|封面|海报|photo|image|poster|cover|png|jpg|jpeg|webp|gif|bmp)/.test(raw)) return 'image';
            if (/(视频|片段|镜头|画面|video|clip|movie|mov|mp4|mkv|avi)/.test(raw)) return 'video';
            return '';
        }

        function readInitialSiteSettings() {
            const node = document.getElementById('siteSettingsPayload');
            if (!node) return {};
            try {
                return JSON.parse(node.textContent || '{}');
            } catch (error) {
                return {};
            }
        }

        function loadRememberedLogin() {
            try {
                const raw = window.localStorage.getItem(rememberedLoginKey);
                const parsed = raw ? JSON.parse(raw) : {};
                return parsed && typeof parsed === 'object' ? parsed : {};
            } catch (error) {
                return {};
            }
        }

        function saveRememberedLogin(enabled, account, password) {
            if (!enabled) {
                window.localStorage.removeItem(rememberedLoginKey);
                return;
            }
            window.localStorage.setItem(rememberedLoginKey, JSON.stringify({
                enabled: true,
                account: account || '',
                password: password || ''
            }));
        }

        function normalizeSiteSettings(raw = {}) {
            const data = raw && typeof raw === 'object' ? raw : {};
            const meta = data.meta && typeof data.meta === 'object' ? data.meta : {};
            const workspace = data.workspace && typeof data.workspace === 'object' ? data.workspace : {};
            const login = data.login && typeof data.login === 'object' ? data.login : {};
            const locked = data.locked && typeof data.locked === 'object' ? data.locked : {};
            const admin = data.admin && typeof data.admin === 'object' ? data.admin : {};
            const agreements = data.agreements && typeof data.agreements === 'object' ? data.agreements : {};
            const agreementUser = agreements.user && typeof agreements.user === 'object' ? agreements.user : {};
            const agreementPrivacy = agreements.privacy && typeof agreements.privacy === 'object' ? agreements.privacy : {};
            const contactEntries = Array.isArray(data.contact_entries)
                ? data.contact_entries
                : (Array.isArray(data.contacts) ? data.contacts : []);
            const siteName = String(data.site_name || meta.site_name || 'VideoFactory');
            return {
                site_name: siteName,
                title: String(data.site_title || data.title || meta.title || `${siteName} 工作台`),
                keywords: String(data.site_keywords || data.keywords || meta.keywords || 'video,ai,generate'),
                description: String(data.site_description || data.description || meta.description || `${siteName} 让创作更自由`),
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
                user_agreement_title: String(data.user_agreement_title || agreementUser.title || '用户协议'),
                user_agreement_content: String(data.user_agreement_content || agreementUser.content || ''),
                privacy_agreement_title: String(data.privacy_agreement_title || agreementPrivacy.title || '隐私协议'),
                privacy_agreement_content: String(data.privacy_agreement_content || agreementPrivacy.content || ''),
                contact_entries: contactEntries.map((item) => String(item || '').trim()).filter(Boolean),
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
            renderContactEntries();
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

        function getPathLeaf(pathValue) {
            const raw = String(pathValue || '').trim().replace(/[\\/]+$/, '');
            if (!raw) return '';
            const parts = raw.split(/[\\/]+/);
            return parts[parts.length - 1] || raw;
        }

        function getMixGenerationResultElement() {
            return document.getElementById('mix_generation_result');
        }

        function renderMixGenerationResult(result = null, options = {}) {
            const box = getMixGenerationResultElement();
            if (!box) return;

            if (!result || typeof result !== 'object') {
                box.innerHTML = '生成完成后，这里会列出本批新草稿和自动清理结果。';
                return;
            }

            const generatedPaths = Array.isArray(result.generated_paths) ? result.generated_paths.filter(Boolean) : [];
            const cleanedPaths = Array.isArray(result.cleaned_paths) ? result.cleaned_paths.filter(Boolean) : [];
            const warnings = Array.isArray(result.warnings) ? result.warnings.filter(Boolean) : [];
            const draftsFolder = String(options.draftsFolder || '').trim();
            const sections = [];

            sections.push(`
                <section class="mix-result-group">
                    <h4 class="mix-result-title">本批新草稿 ${generatedPaths.length} 个</h4>
                    <p class="mix-result-meta">${draftsFolder ? `输出目录：${escapeHtml(draftsFolder)}` : '系统按当前草稿目录生成新的草稿副本。'}</p>
                    ${generatedPaths.length
                        ? `<div class="resource-table-shell mix-result-table">
                            <div class="resource-table-head mix-result-table-head">
                                <span>草稿名称</span>
                                <span>状态</span>
                                <span>草稿路径</span>
                            </div>
                            ${generatedPaths.map((pathValue) => `
                                <article class="resource-table-row mix-result-table-row">
                                    <div class="resource-table-cell"><strong title="${escapeHtml(getPathLeaf(pathValue) || '未命名草稿')}">${escapeHtml(getPathLeaf(pathValue) || '未命名草稿')}</strong></div>
                                    <div class="resource-table-cell"><span class="resource-level-badge">本批新稿</span></div>
                                    <div class="resource-table-cell export-path-cell" title="${escapeHtml(pathValue)}">${escapeHtml(compactPathLabel(pathValue))}</div>
                                </article>
                            `).join('')}
                        </div>`
                        : '<p class="mix-result-summary">任务已完成，但当前返回里没有新草稿路径。</p>'}
                </section>
            `);

            if (cleanedPaths.length) {
                sections.push(`
                    <section class="mix-result-group">
                        <h4 class="mix-result-title">已自动清理旧批次 ${cleanedPaths.length} 个</h4>
                        <p class="mix-result-meta">只会清理由本工具生成的旧草稿，不会动你自己手工创建的草稿。</p>
                        <div class="resource-table-shell mix-result-table">
                            <div class="resource-table-head mix-result-table-head">
                                <span>草稿名称</span>
                                <span>状态</span>
                                <span>草稿路径</span>
                            </div>
                            ${cleanedPaths.map((pathValue) => `
                                <article class="resource-table-row mix-result-table-row">
                                    <div class="resource-table-cell"><strong title="${escapeHtml(getPathLeaf(pathValue) || '旧草稿')}">${escapeHtml(getPathLeaf(pathValue) || '旧草稿')}</strong></div>
                                    <div class="resource-table-cell"><span class="resource-level-badge">已清理</span></div>
                                    <div class="resource-table-cell export-path-cell" title="${escapeHtml(pathValue)}">${escapeHtml(compactPathLabel(pathValue))}</div>
                                </article>
                            `).join('')}
                        </div>
                    </section>
                `);
            }

            if (warnings.length) {
                sections.push(`
                    <section class="mix-result-group">
                        <h4 class="mix-result-title">处理警告</h4>
                        <div class="resource-table-shell mix-result-table">
                            <div class="resource-table-head mix-result-table-head mix-result-warning-head">
                                <span>类型</span>
                                <span>内容</span>
                            </div>
                            ${warnings.map((warning) => `
                                <article class="resource-table-row mix-result-warning-row">
                                    <div class="resource-table-cell"><span class="resource-level-badge">警告</span></div>
                                    <div class="resource-table-cell export-path-cell" title="${escapeHtml(warning)}">${escapeHtml(warning)}</div>
                                </article>
                            `).join('')}
                        </div>
                    </section>
                `);
            }

            box.innerHTML = sections.join('');
        }

        function buildDraftSectionHint(total, limit, noun) {
            if (total <= limit) return `共 ${total} ${noun}`;
            return `共 ${total} ${noun}，更多内容可展开`;
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
                },
                sequence: {
                    short: '每个槽位目录每次会连续取多段视频，先在槽位内拼接，再写回草稿；默认每槽拼接 3 段。',
                    detail: '这是独立的第四种模式。只有它会把同一槽位目录里的多段视频先拼成一个槽位素材，前三种模式仍然保持每次只取 1 个素材。'
                }
            };
            return hintMap[strategy] || hintMap.group;
        }

        function isMixMaterialsRootRequired(strategy = getSelectedReplaceStrategy()) {
            const replaceMaterials = !!document.getElementById('replace_materials')?.checked;
            const replaceAudios = !!document.getElementById('replace_audios')?.checked;
            const replaceTypes = getSelectedReplaceTypes();
            const needsVisual = replaceMaterials && replaceTypes.some((item) => item === 'image' || item === 'video');
            const needsAudio = replaceAudios || replaceTypes.includes('audio');
            return strategy === 'sequence' || needsVisual || needsAudio;
        }

        function getSelectedReplaceTypes() {
            const inputs = Array.from(document.querySelectorAll('input[name="replace_type"]'));
            const values = inputs.filter((input) => input.checked).map((input) => input.value);
            if (!values.length) return [];
            return values;
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
                const slotLabel = getPartitionFolderLabel(name, index);
                return `
                    <button class="material-pill-card${hiddenClass}" type="button" title="${escapeHtml(slotLabel)}">
                        <strong>槽位 ${index + 1}</strong>
                        <span>${escapeHtml(slotLabel)}</span>
                    </button>
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
                const defaultValue = normalizeDraftText(item?.default ?? item ?? '');
                const hiddenClass = index >= limit ? ' is-extra' : '';
                return `
                    <div class="text-strip-item${hiddenClass}">
                        <label for="text_${index}">第 ${index + 1} 段文字</label>
                        <textarea id="text_${index}" rows="3" placeholder="请输入新文字">${escapeHtml(defaultValue)}</textarea>
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
                    <div class="tool-result">支持多行粘贴，也支持 txt / csv 导入。你可以先把整批文案放进下方输入框，再一键写入所有文字槽。</div>
                    <div class="text-batch-shell">
                        <div class="form-group text-batch-main">
                            <label for="text_batch_input">批量文字输入</label>
                            <textarea id="text_batch_input" rows="6" placeholder="每行一段，或直接粘贴 csv / txt 内容"></textarea>
                        </div>
                        <div class="text-batch-actions">
                            <button class="effect-add" type="button" onclick="applyBatchTextTemplate()">批量导入文字</button>
                            <button class="effect-add" type="button" onclick="importTextTemplateFile()">导入 txt/csv</button>
                        </div>
                    </div>
                    <div class="text-strip" data-compact-section="texts">${cards}</div>
                </div>
            `;
        }

        function normalizeDraftText(value) {
            const raw = String(value ?? '').trim();
            if (!raw) return '';
            if (raw.startsWith('{') && raw.includes('"text"')) {
                try {
                    const parsed = JSON.parse(raw);
                    if (parsed && typeof parsed.text === 'string') {
                        return parsed.text;
                    }
                } catch (error) {}
            }
            return raw;
        }

        function renderPartitionTextInputs(partitions = [], textCount = 0) {
            const normalized = [];
            const used = new Set();
            partitions.forEach((item, index) => {
                const label = getPartitionFolderLabel(item, index);
                const key = String(label || '').trim().toLowerCase();
                if (!key || used.has(key)) return;
                used.add(key);
                normalized.push(label);
            });
            const cards = normalized.map((name, index) => `
                <div class="partition-text-card">
                    <label for="partition_text_${index}">${escapeHtml(name)}</label>
                    <textarea id="partition_text_${index}" rows="4" placeholder="每行一段文字，提交时会按分区顺序依次写入前 ${textCount} 个文字槽"></textarea>
                </div>
            `).join('');
            return `
                <div class="materials-strip-card">
                    <div class="strip-head">
                        <h3>按分区整理文字</h3>
                        <div class="strip-head-meta">
                            <span>适合分区混剪时按片头、主体、片尾这类顺序逐段整理文案。</span>
                        </div>
                    </div>
                    <div class="tool-result">直接按分区分别填写，提交时会按当前分区顺序写回对应文字槽。</div>
                    <div class="partition-text-grid">${cards}</div>
                </div>
            `;
        }

        function parseImportedTextLines(raw = '') {
            return String(raw || '')
                .replace(/\uFEFF/g, '')
                .split(/\r?\n/)
                .flatMap((line) => line.split(/,(?=(?:[^\"]*\"[^\"]*\")*[^\"]*$)|，/))
                .map((item) => item.replace(/^"|"$/g, '').trim())
                .filter(Boolean);
        }

        function fillTextInputsFromLines(lines = []) {
            const values = Array.isArray(lines) ? lines : [];
            document.querySelectorAll('#texts_area textarea[id^="text_"]').forEach((node, index) => {
                if (values[index] !== undefined) node.value = values[index];
            });
        }

        function applyBatchTextTemplate() {
            const raw = document.getElementById('text_batch_input')?.value || '';
            const lines = parseImportedTextLines(raw);
            if (!lines.length) {
                notify('请先输入要导入的文字。', 'warn');
                return;
            }
            fillTextInputsFromLines(lines);
            notify(`已导入 ${lines.length} 段文字。`, 'success');
        }

        async function importTextTemplateFile() {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = '.txt,.csv,text/plain,text/csv';
            input.addEventListener('change', async (event) => {
                const file = event.target.files && event.target.files[0];
                if (!file) return;
                const text = await file.text();
                const box = document.getElementById('text_batch_input');
                if (box) box.value = text;
                applyBatchTextTemplate();
            });
            input.click();
        }

        function getWorkspaceSettings() {
            try {
                const parsed = JSON.parse(localStorage.getItem(workspaceSettingsKey) || '{}');
                const sanitized = sanitizeWorkspaceSettings(parsed);
                if (sanitized.changed) {
                    localStorage.setItem(workspaceSettingsKey, JSON.stringify(sanitized.value));
                }
                return sanitized.value;
            } catch (e) {
                return {};
            }
        }

        function setWorkspaceSettings(patch = {}) {
            const next = Object.assign({}, getWorkspaceSettings(), patch || {});
            const sanitized = sanitizeWorkspaceSettings(next);
            localStorage.setItem(workspaceSettingsKey, JSON.stringify(sanitized.value));
            return sanitized.value;
        }

        function sanitizeWorkspaceSettings(raw = {}) {
            const source = raw && typeof raw === 'object' ? raw : {};
            const next = Object.assign({}, source);
            let changed = false;
            workspaceSensitiveSettingKeys.forEach((key) => {
                if (Object.prototype.hasOwnProperty.call(next, key)) {
                    delete next[key];
                    changed = true;
                }
            });
            return { value: next, changed };
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

        function getMaterialTypeLabel(materialType = '') {
            if (materialType === 'image') return '图片';
            if (materialType === 'video') return '视频';
            if (materialType === 'audio') return '音频';
            return '不限类型';
        }

        function inferLayoutFolderMaterialType(folder, index, layout = {}) {
            const strategy = layout.strategy || getSelectedReplaceStrategy();
            if (strategy === 'mix') {
                const selectedTypes = getSelectedReplaceTypes();
                return selectedTypes.length === 1 ? selectedTypes[0] : '';
            }
            const inferred = inferMaterialTypeFromLabel(folder?.label || '');
            if (inferred) return inferred;
            const meta = Array.isArray(materialSlotMeta) ? materialSlotMeta[index] : null;
            const metaType = meta && typeof meta === 'object' ? String(meta.type || '').trim().toLowerCase() : '';
            return ['image', 'video', 'audio'].includes(metaType) ? metaType : '';
        }

        function hydrateMaterialLayout(layout = {}) {
            const folders = Array.isArray(layout.folders) ? layout.folders : [];
            return {
                ...layout,
                folders: folders.map((folder, index) => ({
                    ...folder,
                    material_type: folder?.material_type || inferLayoutFolderMaterialType(folder, index, layout),
                    file_count: Number(folder?.file_count || 0)
                }))
            };
        }

        function clearMaterialLayoutList() {
            currentMaterialLayout = null;
            const box = document.getElementById('materialLayoutList');
            if (box) box.innerHTML = '';
        }

        function renderMaterialLayoutList(layout = null) {
            const box = document.getElementById('materialLayoutList');
            if (!box) return;
            const folders = Array.isArray(layout?.folders) ? layout.folders : [];
            if (!folders.length) {
                box.innerHTML = '';
                return;
            }
            box.innerHTML = folders.map((folder, index) => {
                const materialType = folder.material_type || '';
                const count = Number(folder.file_count || 0);
                const folderLabel = folder.label || `目录 ${index + 1}`;
                const fullPath = String(folder.path || '');
                return `
                    <article class="material-layout-card">
                        <strong title="${escapeHtml(folderLabel)}">${escapeHtml(compactPathLabel(folderLabel, 26))}</strong>
                        <div class="material-layout-chip">${escapeHtml(getMaterialTypeLabel(materialType))}</div>
                        <div class="material-layout-meta">
                            <span>已放素材：${count} 个</span>
                            <span title="${escapeHtml(fullPath)}">${escapeHtml(compactPathLabel(fullPath, 42))}</span>
                        </div>
                        <div class="material-layout-actions">
                            <button class="primary-btn" type="button" onclick="fillMaterialLayoutFolder(${index})">放素材</button>
                        </div>
                    </article>
                `;
            }).join('');
        }

        async function fillMaterialLayoutFolder(index) {
            const layout = currentMaterialLayout;
            const folder = Array.isArray(layout?.folders) ? layout.folders[index] : null;
            const statusEl = document.getElementById('materialLayoutStatus');
            if (!folder?.path) {
                notify('当前目录不存在，请先重新创建目录。', 'warn');
                return;
            }
            try {
                const filePaths = await requestBrowseFiles(folder.material_type || 'all');
                if (!filePaths.length) return;
                if (statusEl) statusEl.textContent = `正在放入素材：${folder.label || folder.path}`;
                const res = await authFetch('/api/materials/fill-folder', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        target_folder: folder.path,
                        file_paths: filePaths,
                        material_type: folder.material_type || 'all'
                    })
                });
                const data = await parseJsonResponse(res, '放素材失败');
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '放素材失败');
                }
                folder.file_count = Number(data.file_count || folder.file_count || 0);
                renderMaterialLayoutList(layout);
                if (statusEl) statusEl.textContent = `${folder.label || '目录'} 已放入 ${data.copied || 0} 个素材。`;
                notify(`已放入 ${data.copied || 0} 个素材。`, 'success');
            } catch (error) {
                if (statusEl) statusEl.textContent = `放素材失败：${error.message || error}`;
                notify(error.message || '放素材失败', 'warn');
            }
        }

        function isLocalRuntimeClient() {
            const host = String(window.location.hostname || '').trim().toLowerCase();
            return host === '127.0.0.1' || host === 'localhost' || host === '::1';
        }

        function getTokenStorage() {
            return isLocalRuntimeClient() ? window.sessionStorage : window.localStorage;
        }

        async function getRuntimeLocalStateValue(key) {
            if (!isLocalRuntimeClient()) return '';
            try {
                const res = await fetch(`/api/runtime/local-state?key=${encodeURIComponent(key)}`);
                if (!res.ok) return '';
                const data = await res.json();
                return data && data.ok ? (data.value || '') : '';
            } catch (e) {
                return '';
            }
        }

        async function setRuntimeLocalStateValue(key, value) {
            if (!isLocalRuntimeClient()) return;
            try {
                await fetch('/api/runtime/local-state', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ key, value: value || '' })
                });
            } catch (e) {}
        }

        async function removeRuntimeLocalStateValue(key) {
            if (!isLocalRuntimeClient()) return;
            try {
                await fetch(`/api/runtime/local-state?key=${encodeURIComponent(key)}`, {
                    method: 'DELETE'
                });
            } catch (e) {}
        }

        async function restoreRuntimeToken() {
            if (!isLocalRuntimeClient()) return '';
            const active = window.sessionStorage.getItem(tokenKey) || '';
            if (active) {
                window.localStorage.removeItem(tokenKey);
                return active;
            }
            const persistFlag = await getRuntimeLocalStateValue(runtimeUserPersistStateKey);
            if (String(persistFlag || '').trim() !== '1') {
                await removeRuntimeLocalStateValue(runtimeUserTokenStateKey);
                window.localStorage.removeItem(tokenKey);
                return '';
            }
            const stored = await getRuntimeLocalStateValue(runtimeUserTokenStateKey);
            if (stored) {
                window.sessionStorage.setItem(tokenKey, stored);
            }
            window.localStorage.removeItem(tokenKey);
            return stored || '';
        }

        function getToken() {
            return getTokenStorage().getItem(tokenKey) || '';
        }

        function setToken(token, options = {}) {
            const value = token || '';
            const persist = !!options.persist;
            const storage = getTokenStorage();
            if (value) {
                storage.setItem(tokenKey, value);
            } else {
                storage.removeItem(tokenKey);
            }
            if (isLocalRuntimeClient()) {
                window.localStorage.removeItem(tokenKey);
                if (value) {
                    if (persist) {
                        void setRuntimeLocalStateValue(runtimeUserTokenStateKey, value);
                        void setRuntimeLocalStateValue(runtimeUserPersistStateKey, '1');
                    } else {
                        void removeRuntimeLocalStateValue(runtimeUserTokenStateKey);
                        void removeRuntimeLocalStateValue(runtimeUserPersistStateKey);
                    }
                } else {
                    void removeRuntimeLocalStateValue(runtimeUserTokenStateKey);
                    void removeRuntimeLocalStateValue(runtimeUserPersistStateKey);
                }
                return;
            }
            if (value) {
                window.localStorage.setItem(tokenKey, value);
            } else {
                window.localStorage.removeItem(tokenKey);
            }
        }

        function clearToken() {
            window.sessionStorage.removeItem(tokenKey);
            window.localStorage.removeItem(tokenKey);
            if (isLocalRuntimeClient()) {
                void removeRuntimeLocalStateValue(runtimeUserTokenStateKey);
                void removeRuntimeLocalStateValue(runtimeUserPersistStateKey);
            }
        }

        function setAuthMessage(msg, isError = true) {
            const el = document.getElementById('authMsg');
            if (!el) return;
            el.style.color = isError ? '#ef4444' : '#16a34a';
            el.textContent = msg || '';
        }

        function openAgreementModal(kind = 'user') {
            const modal = document.getElementById('agreementModal');
            const title = document.getElementById('agreementModalTitle');
            const content = document.getElementById('agreementModalContent');
            if (!modal || !title || !content) return;
            const isPrivacy = kind === 'privacy';
            title.textContent = isPrivacy
                ? (siteSettingsCache.privacy_agreement_title || '隐私协议')
                : (siteSettingsCache.user_agreement_title || '用户协议');
            content.textContent = isPrivacy
                ? (siteSettingsCache.privacy_agreement_content || '暂未配置隐私协议内容。')
                : (siteSettingsCache.user_agreement_content || '暂未配置用户协议内容。');
            modal.classList.add('open');
            modal.style.display = 'flex';
            modal.setAttribute('aria-hidden', 'false');
        }

        function closeAgreementModal() {
            const modal = document.getElementById('agreementModal');
            if (!modal) return;
            modal.classList.remove('open');
            modal.style.display = 'none';
            modal.setAttribute('aria-hidden', 'true');
        }

        function getAnnouncementTodayKey() {
            const now = new Date();
            const y = now.getFullYear();
            const m = String(now.getMonth() + 1).padStart(2, '0');
            const d = String(now.getDate()).padStart(2, '0');
            return `${y}-${m}-${d}`;
        }

        function readAnnouncementDismissState() {
            try {
                const raw = window.localStorage.getItem(announcementDismissKey);
                const parsed = raw ? JSON.parse(raw) : {};
                return parsed && typeof parsed === 'object' ? parsed : {};
            } catch (error) {
                return {};
            }
        }

        function writeAnnouncementDismissState(itemId) {
            window.localStorage.setItem(announcementDismissKey, JSON.stringify({
                date: getAnnouncementTodayKey(),
                id: Number(itemId || 0)
            }));
        }

        function isAnnouncementDismissedToday(itemId) {
            const saved = readAnnouncementDismissState();
            return saved.date === getAnnouncementTodayKey() && Number(saved.id || 0) === Number(itemId || 0);
        }

        function closeAnnouncementModal() {
            const modal = document.getElementById('announcementModal');
            if (!modal) return;
            modal.classList.remove('open');
            modal.style.display = 'none';
            modal.setAttribute('aria-hidden', 'true');
        }

        function renderAnnouncementModal() {
            const item = Array.isArray(announcementState.items) ? announcementState.items[announcementState.index] : null;
            const titleEl = document.getElementById('announcementTitle');
            const metaEl = document.getElementById('announcementMeta');
            const contentEl = document.getElementById('announcementContent');
            const pagerEl = document.getElementById('announcementPager');
            const prevBtn = document.getElementById('announcementPrevBtn');
            const nextBtn = document.getElementById('announcementNextBtn');
            const suppressCheck = document.getElementById('announcementSuppressToday');
            if (!item || !titleEl || !metaEl || !contentEl) return;
            titleEl.textContent = item.title || '公告';
            metaEl.textContent = item.published_at ? new Date(item.published_at).toLocaleDateString() : '最新';
            contentEl.textContent = item.content || '';
            if (pagerEl) pagerEl.textContent = `${announcementState.index + 1} / ${announcementState.items.length}`;
            if (prevBtn) prevBtn.disabled = announcementState.index <= 0;
            if (nextBtn) nextBtn.disabled = announcementState.index >= announcementState.items.length - 1;
            if (suppressCheck) suppressCheck.checked = isAnnouncementDismissedToday(item.id);
        }

        function openAnnouncementModal(index = 0) {
            const modal = document.getElementById('announcementModal');
            if (!modal) return;
            announcementState.index = Math.max(0, Math.min(index, (announcementState.items.length || 1) - 1));
            renderAnnouncementModal();
            modal.classList.add('open');
            modal.style.display = 'flex';
            modal.setAttribute('aria-hidden', 'false');
        }

        function stepAnnouncement(offset) {
            const nextIndex = announcementState.index + Number(offset || 0);
            if (nextIndex < 0 || nextIndex >= announcementState.items.length) return;
            announcementState.index = nextIndex;
            renderAnnouncementModal();
        }

        function toggleAnnouncementTodaySuppressed() {
            const item = announcementState.items[announcementState.index];
            const suppressCheck = document.getElementById('announcementSuppressToday');
            if (!item || !suppressCheck) return;
            if (suppressCheck.checked) {
                writeAnnouncementDismissState(item.id);
            } else {
                window.localStorage.removeItem(announcementDismissKey);
            }
        }

        async function maybeShowAnnouncementModal() {
            if (!currentUserInfo?.id) return;
            try {
                const res = await authFetch('/api/announcements');
                const data = await parseJsonResponse(res, '公告读取失败');
                if (!res.ok || !data.ok) return;
                const items = Array.isArray(data.items) ? data.items : [];
                if (!items.length) return;
                announcementState.items = items;
                announcementState.index = 0;
                const latest = items[0];
                const sessionKey = `${currentUserInfo.id}:${latest.id}:${getAnnouncementTodayKey()}`;
                if (announcementState.sessionShownKey === sessionKey) return;
                announcementState.sessionShownKey = sessionKey;
                if (isAnnouncementDismissedToday(latest.id)) return;
                openAnnouncementModal(0);
            } catch (error) {
                console.warn('announcement modal skipped', error);
            }
        }

        function renderContactEntries() {
            const box = document.getElementById('accountContactList');
            if (!box) return;
            const items = Array.isArray(siteSettingsCache.contact_entries) ? siteSettingsCache.contact_entries : [];
            box.classList.add('account-contact-shell');
            box.innerHTML = items.length
                ? `
                    <div class="resource-table-shell contact-entry-table">
                        <div class="resource-table-head">
                            <span>类型</span>
                            <span>联系方式 / 群号</span>
                        </div>
                        ${items.map((item) => `
                            <article class="resource-table-row">
                                <div class="resource-table-cell"><span class="resource-level-badge">官方渠道</span></div>
                                <div class="resource-table-cell"><strong>${escapeHtml(item)}</strong></div>
                            </article>
                        `).join('')}
                    </div>
                `
                : '<div class="tool-result">管理员暂未配置联系渠道。</div>';
        }

        function getDuoCategoryLabel(category = '') {
            return DUO_CATEGORY_LABELS[category] || category || 'Duo 素材';
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
                `Duo 素材中心 ${runtimeFeatures.duo ? '可用' : '未开放'}`,
                `AI 漫剧草稿 ${runtimeFeatures.manga ? '可用' : '未开放'}`,
                `OpenClaw 接入 ${runtimeFeatures.openclaw ? '已保留' : '未开放'}`
            ];
            return items.join(' / ');
        }

        function renderCommercialSummary() {
            const lockedRuntime = document.getElementById('lockedFeatureRuntime');
            const workspaceQuotaBadge = document.getElementById('workspaceQuotaBadge');

            const disabledFlags = [];
            if (!runtimeFeatures.duo) disabledFlags.push('Duo 素材中心');
            if (!runtimeFeatures.manga) disabledFlags.push('AI 漫剧草稿');
            const disabledHint = disabledFlags.length
                ? `当前版本暂未开放：${disabledFlags.join('、')}。`
                : '';

            if (lockedRuntime) {
                lockedRuntime.textContent = disabledHint;
                lockedRuntime.style.display = disabledHint ? 'block' : 'none';
            }

            if (workspaceQuotaBadge) {
                if (!currentUserInfo) {
                    workspaceQuotaBadge.textContent = '登录后显示会员状态';
                    workspaceQuotaBadge.className = 'workspace-badge workspace-badge-soft';
                } else {
                    const tier = currentUserInfo.is_vip ? 'VIP会员' : '试用用户';
                    const remain = Number(currentUserInfo.remaining ?? 0);
                    if (currentUserInfo.is_vip) {
                        workspaceQuotaBadge.textContent = `${tier} / 无限使用`;
                        workspaceQuotaBadge.className = 'workspace-badge workspace-badge-accent';
                    } else {
                        workspaceQuotaBadge.textContent = `${tier} / 剩余 ${remain} 次`;
                        workspaceQuotaBadge.className = remain > 0
                            ? 'workspace-badge workspace-badge-accent'
                            : 'workspace-badge workspace-badge-warn';
                    }
                }
            }
        }

        function renderVipRules() {
            const rules = accountOverview?.vip_rules || {};
            const usagePolicy = rules.usage_policy || {};
            const defaultQuota = rules.default_user_quota ?? 0;
            const checkinReward = rules.daily_checkin_reward ?? 0;
            const inviteReferrer = rules.invite_referrer_reward ?? 0;
            const inviteeReward = rules.invite_invitee_reward ?? 0;
            const mangaCost = rules.manga_generate_cost ?? 0;
            const defaultQuotaEl = document.getElementById('accountDefaultQuota');
            const checkinRewardEl = document.getElementById('accountCheckinReward');
            const inviteRuleEl = document.getElementById('accountInviteRule');
            const mangaCostEl = document.getElementById('accountMangaCost');
            const rulesText = document.getElementById('accountVipRulesText');
            const usagePolicyEl = document.getElementById('accountUsagePolicyList');
            if (defaultQuotaEl) defaultQuotaEl.textContent = `${defaultQuota} 次`;
            if (checkinRewardEl) checkinRewardEl.textContent = `${checkinReward} 次`;
            if (inviteRuleEl) inviteRuleEl.textContent = `${inviteReferrer}% / ${inviteeReward}%`;
            if (mangaCostEl) mangaCostEl.textContent = `${mangaCost} 次`;
            if (rulesText) {
                rulesText.textContent = [
                    `新用户首次注册可获得 ${defaultQuota} 次体验次数`,
                    `每日签到可领取 ${checkinReward} 次`,
                    `邀请奖励会在好友首次开通会员后生效，邀请人加赠 ${inviteReferrer}% ，好友加赠 ${inviteeReward}%`,
                    `AI 漫剧每次生成消耗 ${mangaCost} 次`
                ].join('\n');
            }
            if (usagePolicyEl) {
                const countItems = Array.isArray(usagePolicy.count_consuming_actions) ? usagePolicy.count_consuming_actions : [];
                const gainItems = Array.isArray(usagePolicy.quota_gain_actions) ? usagePolicy.quota_gain_actions : [];
                const vipGainItems = Array.isArray(usagePolicy.vip_gain_actions) ? usagePolicy.vip_gain_actions : [];
                const freeItems = Array.isArray(usagePolicy.free_actions) ? usagePolicy.free_actions : [];
                const onlineItems = Array.isArray(usagePolicy.online_required_actions) ? usagePolicy.online_required_actions : [];
                const onlineStatus = usagePolicy.online_status || {};
                const offlinePolicy = usagePolicy.offline_policy || {};
                const lines = [
                    '扣次数功能：',
                    ...(countItems.length
                        ? countItems.map((item) => `- ${item.label}：${item.cost_display}${item.online_required ? '，需联网校验' : ''}`)
                        : ['- 暂无']),
                    '',
                    '加次数来源：',
                    ...(gainItems.length
                        ? gainItems.map((item) => `- ${item.label}：${item.description}`)
                        : ['- 暂无']),
                    '',
                    'VIP 时长变化：',
                    ...(vipGainItems.length
                        ? vipGainItems.map((item) => `- ${item.label}：${item.description}`)
                        : ['- 暂无']),
                    '',
                    '免费功能：',
                    ...(freeItems.length
                        ? freeItems.map((item) => `- ${item.label}：${item.description}`)
                        : ['- 暂无']),
                    '',
                    `联网校验状态：${onlineStatus.ok === false ? '当前不可用' : '正常'}`
                ];
                if (onlineItems.length) {
                    lines.push(`联网后才能执行：${onlineItems.map((item) => item.label).join('、')}`);
                }
                if (offlinePolicy.message) {
                    lines.push(offlinePolicy.message);
                }
                usagePolicyEl.textContent = lines.join('\n');
            }
        }

        async function loadLicenseCardTypes() {
            const box = document.getElementById('accountCardTypeList');
            if (!box) return;
            box.textContent = '正在读取卡类型说明。';
            const requestSeq = ++licenseCardTypesRequestSeq;
            let timeoutId = 0;
            try {
                const controller = new AbortController();
                timeoutId = window.setTimeout(() => controller.abort(), 10000);
                const res = await authFetch(`/api/license/card-types?_t=${Date.now()}`, {
                    headers: {'Accept': 'application/json'},
                    signal: controller.signal
                });
                const data = await parseJsonResponse(res, '读取失败');
                if (requestSeq !== licenseCardTypesRequestSeq) return;
                if (!res.ok || !data.ok) throw new Error(data.error || '读取失败');
                const items = Array.isArray(data.items) ? data.items : [];
                if (!items.length) {
                    box.textContent = '当前没有卡类型说明。';
                    return;
                }
                box.innerHTML = `
                    <div class="license-card-type-table">
                        <div class="license-card-type-head">
                            <span>卡类型</span>
                            <span>时长</span>
                            <span>设备数</span>
                            <span>转移次数</span>
                            <span>赠送次数</span>
                        </div>
                        ${items.map((item) => `
                            <div class="license-card-type-item">
                                <strong>${escapeHtml(item.card_type || '-')}</strong>
                                <span>${escapeHtml(`${item.duration_days || 0} 天`)}</span>
                                <span>${escapeHtml(`${item.device_limit || 1} 台`)}</span>
                                <span>${escapeHtml(`${item.transfer_times || 0} 次`)}</span>
                                <span>${escapeHtml(`${item.bonus_points || 0} 次附赠`)}</span>
                            </div>
                        `).join('')}
                    </div>
                `;
            } catch (error) {
                if (requestSeq !== licenseCardTypesRequestSeq) return;
                const message = error?.name === 'AbortError' ? '读取超时，请稍后重试。' : (error.message || error);
                box.textContent = `卡类型读取失败：${message}`;
            } finally {
                if (timeoutId) window.clearTimeout(timeoutId);
            }
        }

        function renderInviteOverview(source = null) {
            const invite = source || currentUserInfo?.invite || accountOverview?.invite || {};
            const inviteCountEl = document.getElementById('inviteCount');
            const inviteRewardEl = document.getElementById('inviteRewardTotal');
            const inviteSummary = document.getElementById('inviteSummaryText');
            const inviteRecent = document.getElementById('inviteRecentList');
            const referrerName = document.getElementById('userReferrerName');
            const referrerRewardTotal = Number(invite.referrer_reward_total ?? 0);
            const inviteeRewardTotal = Number(invite.invitee_reward_total ?? 0);
            const totalRewardDays = referrerRewardTotal + inviteeRewardTotal;
            if (inviteCountEl) inviteCountEl.textContent = invite.invited_count ?? 0;
            if (inviteRewardEl) inviteRewardEl.textContent = totalRewardDays;
            if (referrerName) {
                const name = currentUserInfo?.referrer_username || '-';
                referrerName.textContent = name === '-' || !name ? '未绑定邀请人' : `邀请人：${name}`;
            }
            if (inviteSummary) {
                inviteSummary.textContent = [
                    `邀请激活奖励：被邀请人首次激活会员后，邀请人按开卡时长的 ${invite.referrer_reward ?? 0}% 加赠 VIP`,
                    `受邀加赠：被邀请人首次激活会员后，自己按开卡时长的 ${invite.invitee_reward ?? 0}% 加赠 VIP`,
                    `我的累计邀请奖励：${referrerRewardTotal} 天`,
                    `我的受邀加赠奖励：${inviteeRewardTotal} 天`,
                    `奖励累计到账：${totalRewardDays} 天`
                ].join('\n');
            }
            if (inviteRecent) {
                const items = Array.isArray(invite.recent_invited_users) ? invite.recent_invited_users : [];
                inviteRecent.textContent = items.length
                    ? items.map((item) => `${item.username || '未命名用户'}  ${item.created_at ? new Date(item.created_at).toLocaleString() : '-'}`).join('\n')
                    : '还没有邀请记录。';
            }
        }

        function applyRuntimeFeatureVisibility() {
            const mangaNotice = document.getElementById('mangaFeatureNotice');
            const mangaContent = document.getElementById('mangaFeatureContent');
            const mangaSidebarLink = document.getElementById('aiMangaSidebarLink');
            const duoSection = document.getElementById('duoSection');
            const duoNotice = document.getElementById('duoFeatureNotice');
            const duoSidebarLink = document.getElementById('duoSidebarLink');

            if (!runtimeFeatures.manga) {
                if (mangaNotice) {
                    mangaNotice.style.display = 'block';
                    mangaNotice.textContent = 'AI 漫剧暂未开放，开放后会在这里直接生成草稿、场景目录和分镜说明。';
                }
                if (mangaContent) mangaContent.style.display = 'none';
                if (mangaSidebarLink) mangaSidebarLink.classList.add('is-disabled');
            } else {
                if (mangaNotice) mangaNotice.style.display = 'none';
                if (mangaContent) mangaContent.style.display = 'block';
                if (mangaSidebarLink) mangaSidebarLink.classList.remove('is-disabled');
            }

            if (!runtimeFeatures.duo) {
                if (duoNotice) {
                    duoNotice.style.display = 'block';
                    duoNotice.textContent = 'Duo 素材中心暂未开放，开放后可在这里搜索素材、预览结果并直接加入当前草稿。';
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
            if (!getToken()) {
                openAuthModal();
                return;
            }
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
                badge.textContent = '未选草稿';
                return;
            }
            const name = currentDraftPath.split(/[\\/]/).filter(Boolean).pop() || currentDraftPath;
            const versionMap = {
                all: '自动识别',
                jianying: '剪映',
                capcut: 'CapCut 国际版'
            };
            badge.textContent = `草稿 ${versionMap[currentDraftVersion] || '自动识别'} / ${name}`;
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
                if (status) {
                    if (message) {
                        status.textContent = message;
                    } else if (currentDraftPath) {
                        const draftName = currentDraftPath.split(/[\\/]/).filter(Boolean).pop() || currentDraftPath;
                        status.textContent = `当前草稿：${draftName}`;
                    } else {
                        status.textContent = '请先从下方选择草稿。';
                    }
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
            activateSecondaryTab('effects_section', activeTarget, {syncNav: false});
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
            const ready = currentDraftInfoPath && currentDraftInfoPath === draftPath;
            const needsFolder = isMixMaterialsRootRequired();
            submitBtn.disabled = !(hasToken && draftPath && ready && (!needsFolder || folderPath));
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
                    materialsTitle: '第 2 步：确认草稿槽位顺序',
                    materialsDesc: '已识别槽位，后续目录需要一一对应',
                    folderTitle: '第 3 步：选择素材总目录',
                    folderDesc: '总目录下请按槽位拆分子目录，顺序与草稿槽位保持一致。每个子目录可放多条视频，系统会按批量数量轮换。',
                    advancedTitle: '第 4 步：生成与替换设置',
                },
                mix: {
                    panelTitle: '混剪裂变替换',
                    panelSub: '所有片段共用一个素材池，系统会按规则随机组合生成多条成片，但每次生成每槽只取一个素材。',
                    primaryTitle: '混剪裂变替换',
                    primaryDesc: '先选参考草稿，再选择统一素材池目录，最后批量裂变生成。',
                    materialsTitle: '第 2 步：确认草稿可替换槽位',
                    materialsDesc: '已识别槽位，系统会从同一素材池随机组合',
                    folderTitle: '第 3 步：选择素材池目录',
                    folderDesc: '一个目录即可放入全部候选素材，图片和视频可混放。素材越多，批量裂变空间越大。',
                    advancedTitle: '第 4 步：裂变与高级设置',
                },
                partition: {
                    panelTitle: '分区混剪裂变',
                    panelSub: '按片头、主体、片尾这类分区精准匹配素材，同时保持原始顺序，每次生成每分区只取一个素材。',
                    primaryTitle: '分区混剪裂变',
                    primaryDesc: '先选参考草稿，再按分区准备目录，最后批量生成。',
                    materialsTitle: '第 2 步：确认分区槽位',
                    materialsDesc: '已识别分区槽位，目录名称需与分区保持一致',
                    folderTitle: '第 3 步：选择分区总目录',
                    folderDesc: '总目录下请按分区名称建立子目录，适合片头主体片尾不能混用的场景。每个分区目录可放多条视频轮换。',
                    advancedTitle: '第 4 步：分区高级设置',
                },
                sequence: {
                    panelTitle: '槽位拼接混剪',
                    panelSub: '每个槽位仍按独立目录准备，但生成时会先在该槽位内连续取多段视频拼接，再写回草稿。',
                    primaryTitle: '槽位拼接混剪',
                    primaryDesc: '先选参考草稿，再按槽位准备视频目录，设置单槽拼接段数后开始生成。',
                    materialsTitle: '第 2 步：确认草稿视频槽位',
                    materialsDesc: '已识别可拼接的视频槽位，后续目录需要一一对应',
                    folderTitle: '第 3 步：选择槽位总目录',
                    folderDesc: '总目录下请按槽位拆分子目录。每个槽位目录里可放多段视频，系统会先拼成一个槽位素材再写回草稿。',
                    advancedTitle: '第 4 步：拼接与高级设置',
                }
            };
            return copyMap[strategy] || copyMap.group;
        }

        function setMixStrategy(strategy = 'group') {
            const next = ['group', 'mix', 'partition', 'sequence'].includes(strategy) ? strategy : 'group';
            currentMixStrategy = next;
            updateMixModeUI();
        }

        function syncMixStepVisibility() {
            const dom = getDraftDom();
            const strategy = getSelectedReplaceStrategy();
            const currentCopy = getMixModeCopy(strategy);
            const needsFolder = isMixMaterialsRootRequired(strategy);
            if (dom.folderSection) {
                const shouldShow = needsFolder && (materialsConfig.length > 0 || textsConfig.length > 0);
                dom.folderSection.style.display = shouldShow ? 'block' : 'none';
            }
            const advancedTitle = document.getElementById('mixAdvancedTitle');
            if (advancedTitle && currentCopy.advancedTitle) {
                advancedTitle.textContent = needsFolder ? currentCopy.advancedTitle : currentCopy.advancedTitle.replace('第 4 步', '第 3 步');
            }
        }

        function renderMixModeStatus(strategy = getSelectedReplaceStrategy(), rootLabelMap = null) {
            const currentCopy = getMixModeCopy(strategy);
            const labels = rootLabelMap || {
                group: '素材总目录',
                mix: '素材池目录',
                partition: '分区总目录',
                sequence: '槽位总目录'
            };
            const modeStatusTitle = document.getElementById('mixModeStatusTitle');
            const modeStatusTag = document.getElementById('mixModeStatusTag');
            const modeStatusDetail = document.getElementById('mixModeStatusDetail');
            if (modeStatusTitle) {
                modeStatusTitle.textContent = `${currentCopy.primaryTitle}的实际替换规则`;
            }
            if (modeStatusTag) {
                modeStatusTag.textContent = strategy === 'sequence' ? '每个槽位会先拼接多段视频' : '每次每槽位只取 1 个素材';
            }
            if (modeStatusDetail) {
                const folderTip = isMixMaterialsRootRequired(strategy)
                    ? `当前模式仍需要准备${labels[strategy] || '素材目录'}。`
                    : '当前只替换文字时，不必再选素材目录。';
                modeStatusDetail.textContent = `${getMixConsumptionHint(strategy).detail} ${folderTip}`;
            }
        }

        function syncMixReplaceControls() {
            const strategy = getSelectedReplaceStrategy();
            const replaceMaterialsInput = document.getElementById('replace_materials');
            const replaceTextsInput = document.getElementById('replace_texts');
            const replaceAudiosInput = document.getElementById('replace_audios');
            const replaceMaterials = !!document.getElementById('replace_materials')?.checked;
            const replaceAudios = !!document.getElementById('replace_audios')?.checked;
            const replaceTypeField = document.getElementById('replaceTypeField');
            const replaceModeField = document.getElementById('replaceModeField');
            const replaceTypeInputs = Array.from(document.querySelectorAll('input[name="replace_type"]'));
            const sequenceClipField = document.getElementById('sequenceClipField');
            const partitionTextModeField = document.getElementById('partitionTextModeField');

            if (replaceMaterialsInput) {
                if (strategy === 'sequence') {
                    replaceMaterialsInput.checked = true;
                    replaceMaterialsInput.disabled = true;
                } else {
                    replaceMaterialsInput.disabled = false;
                }
            }
            if (replaceTextsInput && strategy !== 'sequence') {
                replaceTextsInput.disabled = false;
            }
            if (replaceAudiosInput && strategy !== 'sequence') {
                replaceAudiosInput.disabled = false;
            }
            if (replaceTypeInputs.length) {
                if (strategy === 'sequence') {
                    replaceTypeInputs.forEach((input) => {
                        input.checked = input.value === 'video';
                        input.disabled = true;
                    });
                } else {
                    replaceTypeInputs.forEach((input) => {
                        input.disabled = false;
                    });
                }
            }

            if (replaceTypeField) {
                replaceTypeField.style.display = (replaceMaterialsInput?.checked || replaceAudios || strategy === 'sequence') ? '' : 'none';
            }
            if (replaceModeField) {
                replaceModeField.style.display = ((replaceMaterialsInput?.checked || strategy === 'sequence') || replaceAudios) ? '' : 'none';
            }
            if (sequenceClipField) {
                sequenceClipField.style.display = strategy === 'sequence' ? '' : 'none';
            }
            if (partitionTextModeField) {
                partitionTextModeField.style.display = strategy === 'partition' && textsConfig.length ? '' : 'none';
            }
            renderMixModeStatus(strategy);
            syncMixStepVisibility();
            updatePrimaryActionState();
            syncPartitionTextStrategy();
        }

        function syncPartitionTextStrategy() {
            const strategy = getSelectedReplaceStrategy();
            const dom = getDraftDom();
            const partitionMode = document.getElementById('partition_text_mode')?.value || 'global';
            if (dom.textsArea) {
                dom.textsArea.style.display = textsConfig.length && !(strategy === 'partition' && partitionMode === 'partition') ? 'block' : 'none';
            }
            if (dom.partitionTextsArea) {
                dom.partitionTextsArea.style.display = strategy === 'partition' && partitionMode === 'partition' && textsConfig.length ? 'block' : 'none';
            }
        }

        function updateMixModeUI() {
            const strategy = getSelectedReplaceStrategy();
            const rootLabelMap = {
                group: '素材总目录',
                mix: '素材池目录',
                partition: '分区总目录',
                sequence: '槽位总目录'
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
                replaceTypeLabel.textContent = strategy === 'partition' ? '分区素材类型' : strategy === 'sequence' ? '拼接素材类型' : '素材类型';
            }
            if (replaceModeLabel) {
                replaceModeLabel.textContent = strategy === 'group'
                    ? '槽位分配方式'
                    : strategy === 'mix'
                        ? '裂变分配方式'
                        : strategy === 'partition'
                            ? '分区分配方式'
                            : '拼接取样方式';
            }
            if (replaceMode) {
                replaceMode.value = strategy === 'mix' ? 'random' : 'order';
            }
            if (advancedHint) {
                advancedHint.textContent = getMixConsumptionHint(strategy).short;
            }
            renderMixModeStatus(strategy, rootLabelMap);

            syncMixReplaceControls();
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
                partition: '适合多分区模板，每个槽位都要有同名目录；如果文案也按分区整理，可以切到“按分区整理文字”。',
                sequence: '适合一个槽位需要连续吃掉多段短视频的场景。它是独立第四种模式，不会改动前三种的一次取 1 个素材规则。'
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
                const remainEl = document.getElementById('quotaRemaining');
                const totalEl = document.getElementById('quotaTotal');
                const vipEl = document.getElementById('vipExpire');
                const vipBadge = document.getElementById('vipBadge');
                const refCodeEl = document.getElementById('userRefCode');
                const referrerEl = document.getElementById('userReferrer');
                const membershipHintEl = document.getElementById('accountMembershipHint');
                if (remainEl) remainEl.textContent = user.is_vip ? '无限使用' : (user.remaining ?? 0);
                if (totalEl) totalEl.textContent = user.total_generated ?? 0;
                if (vipEl) vipEl.textContent = user.vip_expire_at ? new Date(user.vip_expire_at).toLocaleString() : '-';
                if (refCodeEl) refCodeEl.textContent = user.ref_code || '-';
                if (referrerEl) referrerEl.textContent = user.referrer_id ? `已绑定 #${user.referrer_id}` : '未绑定上级';
                if (membershipHintEl) {
                    membershipHintEl.textContent = user.is_vip
                        ? 'VIP 时效生效中，可无限使用'
                        : '按试用规则使用';
                }
                const copyBtn = document.getElementById('copyRefCodeBtn');
                if (copyBtn) copyBtn.disabled = !user.ref_code;
                if (vipBadge) {
                    vipBadge.textContent = user.membership_label || (user.is_vip ? 'VIP会员' : '试用用户');
                    vipBadge.style.background = user.is_vip ? '#e8f1ff' : '#eef3f8';
                    vipBadge.style.color = user.is_vip ? '#1557d6' : '#475569';
                }
                const cardTypeBox = document.getElementById('accountCardTypeList');
                if (cardTypeBox) cardTypeBox.textContent = '正在读取卡类型说明。';
                renderInviteOverview(user.invite || null);
                loadLicenseStatus();
                loadLicenseCardTypes();
                loadMangaTemplates().catch(() => {});
                loadMangaHistory().catch(() => {});
                loadSiteSettings().catch(() => {});
                loadPointsOverview();
                fillResourceMembership();
                loadResourceExchangeMyPosts();
                closeAuthModal();
                window.setTimeout(() => {
                    maybeShowAnnouncementModal();
                }, 120);
                window.setTimeout(() => {
                    if (currentUserInfo) loadLicenseCardTypes();
                }, 0);
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
                renderInviteOverview(null);
                fillResourceMembership();
                renderResourceMyPosts([]);
                announcementState.sessionShownKey = '';
                closeAnnouncementModal();
                const cardTypeBox = document.getElementById('accountCardTypeList');
                if (cardTypeBox) cardTypeBox.textContent = '登录后查看卡类型说明。';
                loadMangaTemplates().catch(() => {});
                loadMangaHistory().catch(() => {});
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
            const isVipUser = !!(currentUserInfo?.is_vip || overview.quota?.is_vip);
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
            if (costEl) costEl.textContent = isVipUser ? '0' : Math.abs(Number(overview.today_cost || 0));
            if (checkinBtn) {
                checkinBtn.disabled = !currentUserInfo || checkedIn;
                checkinBtn.textContent = checkedIn ? '今日已签到' : '立即签到';
            }
            if (actionMsg && currentUserInfo) {
                actionMsg.textContent = checkedIn
                    ? `今天已完成签到，连续签到 ${overview.streak_days ?? 0} 天。`
                    : `今天签到可领取 ${overview.checkin_reward ?? 0} 次。服务器日期：${overview.server_day || '-'}`;
            }
            renderPointsLogList(overview.recent_logs || []);
            renderVipRules();
            renderInviteOverview(overview.invite || currentUserInfo?.invite || null);
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

        let deviceFingerprintPromise = null;

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

        async function getDeviceFingerprintPayload() {
            if (deviceFingerprintPromise) return deviceFingerprintPromise;
            deviceFingerprintPromise = (async () => {
                const fallback = {
                    fingerprint: buildDeviceFingerprint(),
                    label: 'Web Workspace'
                };
                const host = String(window.location.hostname || '').toLowerCase();
                if (!['127.0.0.1', 'localhost', '::1'].includes(host)) {
                    return fallback;
                }
                try {
                    const res = await fetch('/api/runtime/device-fingerprint');
                    const data = await res.json();
                    if (res.ok && data.ok && data.fingerprint) {
                        return {
                            fingerprint: data.fingerprint,
                            label: data.label || 'Desktop Runtime'
                        };
                    }
                } catch (e) {
                }
                return fallback;
            })();
            return deviceFingerprintPromise;
        }

        async function loadLicenseStatus() {
            const statusEl = document.getElementById('licenseStatus');
            if (!statusEl || !getToken()) return;
            statusEl.textContent = '正在查看授权状态...';
            try {
                const res = await authFetch('/api/license/status');
                const data = await parseJsonResponse(res, '读取授权状态失败');
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
                const deviceIdentity = await getDeviceFingerprintPayload();
                const res = await authFetch('/api/license/activate', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        code,
                        device_fingerprint: deviceIdentity.fingerprint,
                        device_label: deviceIdentity.label
                    })
                });
                const data = await parseJsonResponse(res, '激活失败');
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '激活失败');
                }
                if (statusEl) {
                    const expire = data.expire_at ? new Date(data.expire_at).toLocaleString() : '-';
                    const inviteRewards = data.invite_rewards || {};
                    const inviteLines = [];
                    if (inviteRewards.referrer_reward) inviteLines.push(`邀请人加赠：${inviteRewards.referrer_reward} 天`);
                    if (inviteRewards.invitee_reward) inviteLines.push(`受邀加赠：${inviteRewards.invitee_reward} 天`);
                    statusEl.textContent = [
                        '激活成功',
                        `到期时间：${expire}`,
                        `转移剩余：${data.transfer_times_left || 0}`,
                        ...inviteLines
                    ].join('\n');
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

        async function parseJsonResponse(res, fallbackMessage = '请求失败') {
            const backup = typeof res?.clone === 'function' ? res.clone() : null;
            try {
                return await res.json();
            } catch (error) {
                const text = await (backup ? backup.text() : res.text()).catch(() => '');
                const normalized = String(text || '').replace(/\s+/g, ' ').trim();
                const snippet = normalized
                    ? normalized.replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120)
                    : '';
                throw new Error(snippet || fallbackMessage);
            }
        }

        async function requestBrowseFolder() {
            const response = await fetch('/api/browse-folder', {method: 'POST'});
            const data = await parseJsonResponse(response, '目录选择失败');
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || '目录选择失败');
            }
            return data.folder || '';
        }

        async function requestBrowseFile() {
            const response = await fetch('/api/browse-file', {method: 'POST'});
            const data = await parseJsonResponse(response, '文件选择失败');
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || '文件选择失败');
            }
            return data.file || '';
        }

        async function requestBrowseFiles(materialType = 'all') {
            const response = await fetch('/api/browse-files', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({material_type: materialType || 'all'})
            });
            const data = await parseJsonResponse(response, '文件选择失败');
            if (!response.ok || data.ok === false) {
                throw new Error(data.error || '文件选择失败');
            }
            return Array.isArray(data.files) ? data.files : [];
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
            if (id === 'export_result' || id === 'export_shared_result') {
                const shared = ensureExportSharedResultBox();
                if (shared) shared.textContent = message || '';
                const legacy = document.getElementById('export_result');
                if (legacy) legacy.textContent = message || '';
                return;
            }
            const el = document.getElementById(id);
            if (el) el.textContent = message || '';
        }

        function ensureExportSharedResultBox() {
            let box = document.getElementById('export_shared_result');
            if (box) return box;
            const panel = document.getElementById('panel-export');
            if (!panel) return document.getElementById('export_result');
            const shell = document.createElement('section');
            shell.className = 'tool-card';
            shell.id = 'export_shared_result_shell';
            shell.innerHTML = `
                <div class="tool-head"><div><h3>导出结果</h3></div></div>
                <div id="export_shared_result" class="tool-result">导出结果会显示在这里。</div>
            `;
            const anchor = panel.querySelector('.module-head');
            if (anchor && anchor.nextSibling) {
                panel.insertBefore(shell, anchor.nextSibling);
            } else {
                panel.appendChild(shell);
            }
            return document.getElementById('export_shared_result');
        }

        function renderAiPromptKeyOptions(items = []) {
            const select = document.getElementById('ai_key_id');
            if (!select) return;
            const activeItems = items.filter((item) => item.is_active !== false);
            select.innerHTML = ['<option value="">自动选择可用账号</option>']
                .concat(activeItems.map((item) => `<option value="${item.id}">${item.key_name || item.provider_code || ('Key #' + item.id)}</option>`))
                .join('');
        }

        async function discoverDrafts(targetShell = null, renderInModal = isDraftPickerOpen(), forceRefresh = false) {
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
            summary.textContent = '正在读取最近草稿，请稍候...';
            list.innerHTML = '<div class="tool-result">正在读取最近草稿...</div>';
            try {
                const query = forceRefresh ? '/api/drafts/discover?limit=20&refresh=1' : '/api/drafts/discover?limit=20';
                const res = await authFetch(query);
                const data = await parseJsonResponse(res, '草稿扫描失败');
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
                    window.__vfDiscoveredDraftsAll = [];
                    return;
                }
                const visibleDrafts = renderInModal ? filteredDrafts : filteredDrafts.slice(0, 3);
                summary.textContent = renderInModal
                    ? `已发现 ${filteredDrafts.length} 个草稿，可直接选择。`
                    : `已发现 ${filteredDrafts.length} 个草稿。`;
                list.innerHTML = visibleDrafts.map((item, idx) => `
                    <div class="draft-item ${activePath && activePath === item.path ? 'active' : ''}" data-draft-index="${idx}" role="button" tabindex="0">
                        <div class="draft-item-head"><strong class="draft-item-title" title="${escapeHtml(item.name || '未命名草稿')}">${item.name || '未命名草稿'}</strong><span class="draft-use-tag">点击即用</span></div>
                        <div class="draft-meta">来源：${item.source || '-'}\n更新时间：${new Date(item.updated_at).toLocaleString()}\n路径：${item.path}</div>
                    </div>
                `).join('');
                if (!renderInModal && filteredDrafts.length > visibleDrafts.length) {
                    list.innerHTML += `<div class="draft-more-note">其余 ${filteredDrafts.length - visibleDrafts.length} 个草稿已收起，可在弹窗查看完整列表。</div>`;
                }
                window.__vfDiscoveredDrafts = visibleDrafts;
                window.__vfDiscoveredDraftsAll = filteredDrafts;
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
                setToolResult('clip_result', '请先读取已选草稿，再应用微调。');
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
                    `草稿：${data.draft_name || summary.draft_name || '已更新已选草稿'}`,
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
            const format = document.getElementById('export_format')?.value || 'mp4';
            const resolution = document.getElementById('export_resolution')?.value || '1080p';
            const fps = parseInt(document.getElementById('export_fps')?.value || '30', 10);
            const exportEnabled = !!document.getElementById('export_enable')?.checked;
            const batchCount = parseInt(document.getElementById('batch_count')?.value || '1', 10);
            const queued = exportDraftQueue.length;
            const lines = [
                '这是导出预览，不会立即执行导出。',
                `导出目录：${exportDir || '尚未填写，建议先设置固定输出目录'}`,
                `导出执行：${exportEnabled ? '生成后自动导出' : '仅生成草稿，不直接导出'}`,
                `格式设置：${format.toUpperCase()} / ${resolution} / ${fps} FPS`,
                `当前待导出草稿：${queued} 个`,
                `如果你在批量混剪里生成 ${batchCount} 条，这里建议先抽检 1 条，再继续批量导出。`
            ];
            setToolResult('export_result', lines.join('\n'));
        }

        function renderExportDraftQueue() {
            const summary = document.getElementById('export_queue_summary');
            const list = document.getElementById('export_queue_list');
            if (!summary || !list) return;
            if (!exportDraftQueue.length) {
                summary.textContent = '当前还没有待导出的草稿。';
                list.innerHTML = '<div class="tool-result">待导出草稿会显示在这里。</div>';
                return;
            }
            summary.textContent = `已加入 ${exportDraftQueue.length} 个待导出草稿。`;
            list.innerHTML = `
                <div class="resource-table-shell export-table-shell">
                    <div class="resource-table-head export-table-head">
                        <span>草稿名称</span>
                        <span>来源</span>
                        <span>草稿路径</span>
                        <span>操作</span>
                    </div>
                    ${exportDraftQueue.map((item, index) => `
                        <article class="resource-table-row export-table-row">
                            <div class="resource-table-cell"><strong title="${escapeHtml(item.name || '未命名草稿')}">${escapeHtml(item.name || '未命名草稿')}</strong></div>
                            <div class="resource-table-cell"><span class="resource-level-badge">${escapeHtml(item.source || '本机草稿')}</span></div>
                            <div class="resource-table-cell export-path-cell" title="${escapeHtml(item.path || '')}">${escapeHtml(compactPathLabel(item.path || ''))}</div>
                            <div class="resource-table-cell"><button class="effect-add" type="button" onclick="removeExportDraftAt(${index})">移除</button></div>
                        </article>
                    `).join('')}
                </div>
            `;
        }

        function removeExportDraftAt(index) {
            exportDraftQueue.splice(index, 1);
            renderExportDraftQueue();
        }

        function addCurrentDraftToExportQueue() {
            const draftPath = getDraftElement('path')?.value?.trim() || currentDraftPath || '';
            if (!draftPath) {
                setToolResult('export_result', '请先选择已选草稿，再加入待导出列表。');
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
                setToolResult('export_result', '已选草稿已加入待导出列表。');
        }

        function addDiscoveredDraftsToExportQueue() {
            const drafts = Array.isArray(window.__vfDiscoveredDraftsAll) ? window.__vfDiscoveredDraftsAll : [];
            if (!drafts.length) {
                setToolResult('export_result', '还没有最近发现的草稿，请先打开草稿选择器刷新。');
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
                list.innerHTML = '<div class="tool-result">加入后的草稿会显示在这里。</div>';
                return;
            }
            summary.textContent = `已加入 ${splitDraftQueue.length} 个草稿。`;
            list.innerHTML = `
                <div class="resource-table-shell export-table-shell">
                    <div class="resource-table-head export-table-head">
                        <span>草稿名称</span>
                        <span>来源</span>
                        <span>草稿路径</span>
                        <span>操作</span>
                    </div>
                    ${splitDraftQueue.map((item, index) => `
                        <article class="resource-table-row export-table-row">
                            <div class="resource-table-cell"><strong title="${escapeHtml(item.name || '未命名草稿')}">${escapeHtml(item.name || '未命名草稿')}</strong></div>
                            <div class="resource-table-cell"><span class="resource-level-badge">${escapeHtml(item.source || '本机草稿')}</span></div>
                            <div class="resource-table-cell export-path-cell" title="${escapeHtml(item.path || '')}">${escapeHtml(compactPathLabel(item.path || ''))}</div>
                            <div class="resource-table-cell"><button class="effect-add" type="button" onclick="removeSplitDraftAt(${index})">移除</button></div>
                        </article>
                    `).join('')}
                </div>
            `;
        }

        function compactPathLabel(path = '', maxLength = 72) {
            const clean = String(path || '');
            const max = Math.max(24, Number(maxLength || 72));
            if (clean.length <= max) return clean;
            const head = Math.max(10, Math.floor((max - 5) / 2));
            const tail = Math.max(10, max - 5 - head);
            return `${clean.slice(0, head)} ... ${clean.slice(-tail)}`;
        }

        function removeSplitDraftAt(index) {
            splitDraftQueue.splice(index, 1);
            renderSplitDraftQueue();
        }

        function addDiscoveredDraftsToSplitQueue() {
            const drafts = Array.isArray(window.__vfDiscoveredDraftsAll) ? window.__vfDiscoveredDraftsAll : [];
            if (!drafts.length) {
                setToolResult('split_multi_result', '还没有最近发现的草稿，请先打开草稿选择器刷新。');
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
                partitionTextsArea: document.getElementById('partition_texts_area'),
                folderSection: document.getElementById('folder_section'),
                optionsSection: document.getElementById('options_section'),
                effectsSection: document.getElementById('effects_section')
            };
        }

        function resetDraftInfo(message = '') {
            currentDraftPath = '';
            currentDraftInfoPath = '';
            currentDraftVersion = getDraftElement('version')?.value || 'all';
            materialsConfig = [];
            materialSlotMeta = [];
            textsConfig = [];
            draftTrackMeta = [];
            clearMaterialLayoutList();
            const dom = getDraftDom();
            if (dom.materialsArea) dom.materialsArea.style.display = 'none';
            if (dom.materialsList) dom.materialsList.innerHTML = '';
            if (dom.textsArea) {
                dom.textsArea.innerHTML = '';
                dom.textsArea.style.display = 'none';
            }
            if (dom.partitionTextsArea) {
                dom.partitionTextsArea.innerHTML = '';
                dom.partitionTextsArea.style.display = 'none';
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
            if (dom.draftStatus) dom.draftStatus.textContent = '正在整理已选草稿内容...';

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
                currentDraftInfoPath = draftPath;
                currentDraftVersion = getDraftElement('version')?.value || inferDraftVersion(draftPath);
                materialsConfig = data.materials || [];
                materialSlotMeta = Array.isArray(data.material_items) ? data.material_items : [];
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
                    }
                    if (dom.partitionTextsArea) {
                        dom.partitionTextsArea.innerHTML = renderPartitionTextInputs(materialsConfig, textsConfig.length);
                    }
                } else {
                    if (dom.textsArea) dom.textsArea.style.display = 'none';
                    if (dom.partitionTextsArea) dom.partitionTextsArea.style.display = 'none';
                }

                if (materialsConfig.length > 0 || textsConfig.length > 0) {
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
                    dom.draftStatus.textContent = `当前草稿：${matCount} 个素材槽 / ${textCount} 段文字`;
                }
                syncDraftShellValues(dom.draftStatus?.textContent || '');
                updateWorkspaceDraftBadge();
                toggleProtectedUI(!!getToken());
                updatePrimaryActionState();
                updateMixModeUI();
                syncMixStepVisibility();
                syncPartitionTextStrategy();
            } catch (error) {
                resetDraftInfo(`草稿读取失败：${error.message}`);
            }
        }

        async function selectFolder() {
            const folder = await requestBrowseFolder();
            document.getElementById('folder_path').value = folder || '';
            if (folder) {
                pushRecentMaterialFolder(folder);
                setWorkspaceSettings({last_materials_root: folder});
            }
            updatePrimaryActionState();
        }

        function buildAssistantContext() {
            return {
                draft_path: getDraftElement('path')?.value?.trim() || currentDraftPath || '',
                materials_root: document.getElementById('folder_path')?.value?.trim() || '',
                strategy: getSelectedReplaceStrategy(),
                slots: materialsConfig.slice(),
                text_count: textsConfig.length
            };
        }

        async function createMaterialLayout() {
            if (!getToken()) {
                notify('请先登录后再创建素材目录。', 'warn');
                return;
            }
            const statusEl = document.getElementById('materialLayoutStatus');
            const context = buildAssistantContext();
            if (!context.draft_path) {
                if (statusEl) statusEl.textContent = '请先选择草稿。';
                notify('请先选择草稿。', 'warn');
                return;
            }
            if (!context.materials_root) {
                if (statusEl) statusEl.textContent = '请先选择素材根目录。';
                notify('请先选择素材根目录。', 'warn');
                return;
            }
            if (statusEl) statusEl.textContent = '正在创建素材目录...';
            try {
                const res = await authFetch('/api/materials/create-layout', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(context)
                });
                const data = await res.json();
                if (!res.ok || !data.ok) throw new Error(data.error || '创建失败');
                const layout = data.layout || {};
                const folderInput = document.getElementById('folder_path');
                if (folderInput && layout.root) {
                    folderInput.value = layout.root;
                    pushRecentMaterialFolder(layout.root);
                    setWorkspaceSettings({last_materials_root: layout.root});
                }
                currentMaterialLayout = hydrateMaterialLayout(layout);
                renderMaterialLayoutList(currentMaterialLayout);
                const folderNames = Array.isArray(layout.folders) ? layout.folders.map((item) => item.label || item.path).join(' / ') : '';
                if (statusEl) statusEl.textContent = layout.root ? `目录已创建：${layout.root}${folderNames ? `\n${folderNames}` : ''}` : '目录已创建';
                updatePrimaryActionState();
                notify('素材目录已按草稿创建。', 'success');
            } catch (e) {
                clearMaterialLayoutList();
                if (statusEl) statusEl.textContent = `创建失败：${e.message || e}`;
                notify(e.message || '创建素材目录失败', 'warn');
            }
        }

        async function selectAudioFolder() {
            const input = document.getElementById('audio_folder_path');
            const folder = await requestBrowseFolder();
            if (input) input.value = folder || '';
            if (folder) {
                setWorkspaceSettings({last_audio_root: folder});
            }
        }

        async function selectDraftFolder() {
            const input = getDraftElement('path');
            const folder = await requestBrowseFolder();
            if (input) input.value = folder || '';
            if (folder) {
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
                notify('草稿状态已变化，请重新选择后再试。', 'warn');
                return;
            }
            const batchCount = parseInt(document.getElementById('batch_count').value) || 1;
            if (batchCount < 1 || batchCount > 100) {
                notify('批量生成数量需要在 1 到 100 之间。', 'warn');
                return;
            }

            const replaceMaterials = document.getElementById('replace_materials').checked;
            const replaceTexts = document.getElementById('replace_texts').checked;
            const replaceAudios = document.getElementById('replace_audios')?.checked || false;
            if (!replaceMaterials && !replaceTexts && !replaceAudios) {
                notify('请至少选择一种替换内容。', 'warn');
                return;
            }
            const replaceTypes = getSelectedReplaceTypes();
            const visualTypes = replaceTypes.filter((item) => item === 'image' || item === 'video');
            const effectiveReplaceMaterials = replaceMaterials && visualTypes.length > 0;
            const effectiveReplaceAudios = replaceAudios || replaceTypes.includes('audio');
            if (replaceMaterials && !visualTypes.length && !effectiveReplaceAudios) {
                notify('请至少勾选一种素材类型。', 'warn');
                return;
            }
            const replaceMode = document.getElementById('replace_mode')?.value || 'order';
            const replaceStrategy = getSelectedReplaceStrategy();
            const folderPath = document.getElementById('folder_path')?.value?.trim() || '';
            const partitionTextMode = document.getElementById('partition_text_mode')?.value || 'global';
            const sequenceClipCount = parseInt(document.getElementById('sequence_clip_count')?.value || '3', 10) || 3;
            const audioEnabled = !!document.getElementById('audio_enabled')?.checked;
            const audioFolderPath = document.getElementById('audio_folder_path')?.value?.trim();
            const exportEnabled = !!document.getElementById('export_enable')?.checked;
            const exportPath = document.getElementById('export_dir')?.value?.trim();
            const exportFormat = document.getElementById('export_format')?.value || 'mp4';
            const exportResolution = document.getElementById('export_resolution')?.value || '1080p';
            const exportFps = parseInt(document.getElementById('export_fps')?.value || '30', 10);

            if (replaceStrategy === 'sequence' && (sequenceClipCount < 2 || sequenceClipCount > 12)) {
                notify('槽位拼接段数需要在 2 到 12 之间。', 'warn');
                return;
            }
            if (isMixMaterialsRootRequired(replaceStrategy) && !folderPath) {
                notify('请先选择素材目录。', 'warn');
                return;
            }

            const textsInput = [];
            if (replaceTexts) {
                const globalTexts = [];
                for (let i = 0; i < textsConfig.length; i++) {
                    const input = document.getElementById(`text_${i}`);
                    globalTexts.push(input ? input.value : '');
                }
                let finalTexts = globalTexts.slice();
                if (replaceStrategy === 'partition' && partitionTextMode === 'partition') {
                    const partitionValues = Array.from(document.querySelectorAll('[id^="partition_text_"]'))
                        .flatMap((node) => (node.value || '').split(/\r?\n/).map((line) => line.trim()).filter(Boolean));
                    partitionValues.slice(0, textsConfig.length).forEach((value, index) => {
                        finalTexts[index] = value;
                    });
                }
                finalTexts.forEach((value, index) => {
                    textsInput.push({index, contents: [value], rule: 'order'});
                });
            }

            const payload = {
                draft_path: draftPath,
                materials_root: folderPath,
                texts_input: textsInput,
                batch_count: batchCount,
                replace_materials: effectiveReplaceMaterials,
                replace_texts: replaceTexts,
                replace_audios: effectiveReplaceAudios,
                replace_type: replaceTypes,
                replace_mode: replaceMode,
                replace_strategy: replaceStrategy,
                partition_text_mode: partitionTextMode,
                sequence_clip_count: sequenceClipCount,
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
            renderMixGenerationResult(null);

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
            const fallbackTypes = Object.keys(EFFECT_TYPE_LABELS || {});
            try {
                const res = await authFetch('/api/effects/types');
                const data = await parseJsonResponse(res, '资源类型读取失败');
                const sel = document.getElementById('effect_type');
                if (!sel) return;
                const types = Array.isArray(data.types) && data.types.length ? data.types : fallbackTypes;
                if (types.length) {
                    sel.innerHTML = types
                        .map((t) => `<option value="${t}">${escapeHtml(EFFECT_TYPE_LABELS[t] || t)}</option>`)
                        .join('');
                }
            } catch (e) {
                const sel = document.getElementById('effect_type');
                if (!sel) return;
                if (fallbackTypes.length) {
                    sel.innerHTML = fallbackTypes
                        .map((t) => `<option value="${t}">${escapeHtml(EFFECT_TYPE_LABELS[t] || t)}</option>`)
                        .join('');
                }
            }
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
            const res = await authFetch('/api/effects/list', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({effect_type: effectType, keyword, limit, is_vip: isVip})
            });
            const data = await parseJsonResponse(res, '资源搜索失败');
            resourceCache = data.effects || [];
            renderResourceResults(resourceCache);
        }

        function buildResourceMetaChips(item = {}, extras = []) {
            const chips = [];
            extras.forEach((extra) => {
                if (extra) chips.push(extra);
            });
            if (item?.effect_type) chips.push(item.effect_type);
            if (item?.type && item.type !== item.effect_type) chips.push(item.type);
            if (item?.resource_id) chips.push(`资源ID ${item.resource_id}`);
            else if (item?.effect_id) chips.push(`效果ID ${item.effect_id}`);
            else if (item?.id) chips.push(`编号 ${item.id}`);
            if (item?.is_vip) chips.push('VIP');
            return chips;
        }

        function getDuoPreviewUrl(item = {}) {
            const meta = item?.meta && typeof item.meta === 'object' ? item.meta : {};
            return item?.preview_url
                || item?.preview
                || item?.url
                || meta?.preview_url
                || meta?.url
                || '';
        }

        function pickPreviewUrl(value) {
            if (!value) return '';
            if (typeof value === 'string') {
                return value.trim();
            }
            if (Array.isArray(value)) {
                for (const entry of value) {
                    const candidate = pickPreviewUrl(entry);
                    if (candidate) return candidate;
                }
                return '';
            }
            if (typeof value !== 'object') {
                return '';
            }
            const fields = [
                'preview_url', 'previewUrl', 'preview',
                'cover_url', 'coverUrl', 'cover',
                'thumbnail_url', 'thumbnailUrl', 'thumbnail',
                'thumb_url', 'thumbUrl', 'thumb',
                'poster_url', 'posterUrl', 'poster',
                'snapshot_url', 'snapshotUrl', 'snapshot',
                'icon_url', 'iconUrl', 'icon',
                'image_url', 'imageUrl', 'image',
                'url', 'uri', 'src'
            ];
            for (const field of fields) {
                const candidate = pickPreviewUrl(value[field]);
                if (candidate) return candidate;
            }
            return '';
        }

        function getResourcePreviewUrl(item = {}) {
            const meta = item?.meta && typeof item.meta === 'object' ? item.meta : {};
            return pickPreviewUrl([
                item?.preview_url,
                item?.preview,
                item?.cover_url,
                item?.cover,
                item?.thumbnail_url,
                item?.thumbnail,
                item?.thumb_url,
                item?.thumb,
                item?.poster_url,
                item?.poster,
                item?.snapshot_url,
                item?.snapshot,
                item?.icon_url,
                item?.icon,
                item?.image_url,
                item?.image,
                item?.url,
                item?.uri,
                item?.src,
                item?.images,
                item?.image_list,
                item?.covers,
                item?.resource,
                item?.material,
                item?.extra,
                meta
            ]);
        }

        function renderResourceResults(items) {
            const results = document.getElementById('resource_results');
            if (!results) return;
            if (!items.length) {
                results.innerHTML = '<div class="tool-result">没有找到匹配资源，换个关键词再试试。</div>';
                return;
            }
            results.innerHTML = `
                <div class="resource-table-shell resource-search-table">
                    <div class="resource-table-head">
                        <span>预览</span>
                        <span>资源名称</span>
                        <span>资源标识</span>
                        <span>资源分类</span>
                        <span>附加信息</span>
                        <span>操作</span>
                    </div>
                    ${items.map((item, idx) => {
                        const name = item.name || item.title || '未命名资源';
                        const identifier = item.resource_id || item.effect_id || item.id || '-';
                        const category = item.effect_type || item.type || '-';
                        const previewUrl = getResourcePreviewUrl(item);
                        const chips = buildResourceMetaChips(item)
                            .filter((chip) => chip !== category && chip !== `资源ID ${identifier}` && chip !== `效果ID ${identifier}` && chip !== `编号 ${identifier}`);
                        return `
                            <article class="resource-table-row resource-search-row">
                                <div class="resource-table-cell duo-preview-cell">${previewUrl
                                    ? `<img class="resource-browser-thumb" src="${previewUrl}" alt="${escapeHtml(name)}">`
                                    : '<div class="resource-browser-thumb resource-browser-thumb-empty" title="当前官方资源元数据不含预览图">无预览</div>'}</div>
                                <div class="resource-table-cell resource-search-name"><strong>${escapeHtml(name)}</strong></div>
                                <div class="resource-table-cell"><span>${escapeHtml(identifier)}</span></div>
                                <div class="resource-table-cell"><span>${escapeHtml(category)}</span></div>
                                <div class="resource-table-cell resource-search-meta">${chips.length
                                    ? chips.map((chip) => `<span class="resource-browser-chip">${escapeHtml(chip)}</span>`).join('')
                                    : '<span class="resource-browser-chip">资源库</span>'}</div>
                                <div class="resource-table-cell resource-search-action"><button class="effect-add" type="button" onclick="useResource(${idx})">加入当前效果</button></div>
                            </article>
                        `;
                    }).join('')}
                </div>
            `;
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
            const fallbackCategories = ['video_effects', 'transitions', 'face_effects', 'stickers', 'text_templates'];
            try {
                const res = await authFetch('/api/duo/resources/categories');
                const data = await parseJsonResponse(res, 'Duo 分类读取失败');
                const sel = document.getElementById('duo_category');
                if (sel) {
                    const categories = Array.isArray(data.categories) && data.categories.length
                        ? data.categories.filter(Boolean)
                        : fallbackCategories;
                    const total = Number(data.resource_count || 0);
                    const previousValue = sel.value || '';
                    const allLabel = total > 0 ? `全部分类（${total}）` : '全部分类';
                    sel.innerHTML = [`<option value="">${escapeHtml(allLabel)}</option>`]
                        .concat(categories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(getDuoCategoryLabel(category))}</option>`))
                        .join('');
                    sel.value = previousValue && categories.includes(previousValue) ? previousValue : '';
                }
            } catch (e) {
                const sel = document.getElementById('duo_category');
                if (sel) {
                    sel.innerHTML = ['<option value="">全部分类</option>']
                        .concat(fallbackCategories.map((category) => `<option value="${escapeHtml(category)}">${escapeHtml(getDuoCategoryLabel(category))}</option>`))
                        .join('');
                }
            }
        }

        function renderDuoLists() {
            renderAllEffectLists();
        }

        function toggleDuoFields() {
            // 简化：保持字段可见
        }

        async function searchDuoResources() {
            const category = document.getElementById('duo_category')?.value?.trim() || '';
            const keyword = document.getElementById('duo_keyword')?.value?.trim() || '';
            const limit = parseInt(document.getElementById('duo_limit')?.value || '50', 10);
            const page = parseInt(document.getElementById('duo_page')?.value || '1', 10);
            const offset = (page - 1) * limit;
            const pager = document.getElementById('duo_pager_info');
            const cacheKey = `${category || 'all'}_${keyword}_${limit}_${page}`;
            if (duoPageCache[cacheKey]) {
                const cached = duoPageCache[cacheKey];
                duoCache = cached.items;
                renderDuoResults(cached.items);
                if (pager) pager.innerText = `共 ${cached.total} 条素材，当前第 ${page} 页`;
                return;
            }
            const res = await authFetch('/api/duo/resources/search', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({category: category || null, keyword, limit, offset})
            });
            const data = await parseJsonResponse(res, 'Duo 素材搜索失败');
            const items = data.items || [];
            duoCache = items;
            duoPageCache[cacheKey] = {items, total: data.total || 0};
            renderDuoResults(items);
            if (pager) pager.innerText = `共 ${data.total || 0} 条素材，当前第 ${page} 页`;
        }

        function renderDuoResults(items) {
            const results = document.getElementById('duo_results');
            if (!results) return;
            if (!items.length) {
                results.innerHTML = '<div class="tool-result">没有找到匹配素材，试试更换分类或关键词。</div>';
                return;
            }
            results.innerHTML = `
                <div class="resource-table-shell duo-search-table">
                    <div class="resource-table-head">
                        <span>预览</span>
                        <span>素材名称</span>
                        <span>素材标识</span>
                        <span>素材分类</span>
                        <span>附加信息</span>
                        <span>操作</span>
                    </div>
                    ${items.map((item, idx) => {
                        const previewUrl = getDuoPreviewUrl(item);
                        const preview = previewUrl
                            ? `<img class="resource-browser-thumb" src="${previewUrl}" alt="${escapeHtml(item.name || 'Duo 素材')}">`
                            : '<div class="resource-browser-thumb resource-browser-thumb-empty">Duo</div>';
                        const categoryValue = document.getElementById('duo_category')?.value || item.category || '';
                        const category = getDuoCategoryLabel(categoryValue);
                        const identifier = item.id || item.resource_id || item.effect_id || '-';
                        const chips = buildResourceMetaChips(item, [category])
                            .filter((chip) => chip !== category && chip !== `编号 ${identifier}` && chip !== `资源ID ${identifier}` && chip !== `效果ID ${identifier}`);
                        return `
                            <article class="resource-table-row duo-search-row">
                                <div class="resource-table-cell duo-preview-cell">${preview}</div>
                                <div class="resource-table-cell"><strong>${escapeHtml(item.name || '未命名素材')}</strong></div>
                                <div class="resource-table-cell"><span>${escapeHtml(identifier)}</span></div>
                                <div class="resource-table-cell"><span>${escapeHtml(category)}</span></div>
                                <div class="resource-table-cell duo-search-meta">${chips.length
                                    ? chips.map((chip) => `<span class="resource-browser-chip">${escapeHtml(chip)}</span>`).join('')
                                    : '<span class="resource-browser-chip">Duo 素材</span>'}</div>
                                <div class="resource-table-cell resource-search-action"><button class="effect-add" type="button" onclick="useDuoResource(${idx})">加入当前方案</button></div>
                            </article>
                        `;
                    }).join('')}
                </div>
            `;
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
            const res = await authFetch('/api/duo/cache/refresh', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({resource_path: path})
            });
            const data = await parseJsonResponse(res, '资源索引更新失败');
            if (info) info.innerText = data.ok ? '资源索引已更新，可重新搜索最新素材。' : (data.error || '更新失败');
            duoPageCache = {};
            loadDuoCacheStatus();
        }

        async function loadDuoCacheStatus() {
            const info = document.getElementById('duo_cache_info');
            try {
                const res = await authFetch('/api/duo/cache/status');
                const data = await parseJsonResponse(res, '资源索引状态读取失败');
                if (info) info.innerText = data.exists ? `本地素材索引可用，共 ${data.resource_count || 0} 条素材。` : '暂未发现可用的本地素材索引。';
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
            if (info) info.innerText = data.ok ? `资源包导入成功，共 ${data.count} 条素材。` : (data.error || '导入失败');
            duoPageCache = {};
            loadDuoCacheStatus();
        }

        async function loadFfmpegStatus() {
            const info = document.getElementById('duo_ffmpeg_info');
            try {
                const res = await fetch('/api/duo/ffmpeg/status');
                const data = await res.json();
                if (info) info.innerText = data.ok ? '' : (data.error || '暂未检测到视频处理环境');
            } catch (e) {
                if (info) info.innerText = '';
            }
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
            const loginForm = document.getElementById('loginForm');
            const registerForm = document.getElementById('registerForm');
            const logoutBtn = document.getElementById('logoutBtn');
            const copyRefCodeBtn = document.getElementById('copyRefCodeBtn');
            const activateLicenseBtn = document.getElementById('activateLicenseBtn');
            const dailyCheckinBtn = document.getElementById('dailyCheckinBtn');
            const refreshPointsBtn = document.getElementById('refreshPointsBtn');
            const openBtns = [document.getElementById('openAuthModalBtnHero')].filter(Boolean);
            const loginAgreementCheck = document.getElementById('loginAgreementCheck');
            const registerAgreementCheck = document.getElementById('registerAgreementCheck');
            const loginRememberMe = document.getElementById('loginRememberMe');
            const rememberedLogin = loadRememberedLogin();

            if (rememberedLogin.enabled) {
                if (document.getElementById('loginAccount')) document.getElementById('loginAccount').value = rememberedLogin.account || '';
                if (document.getElementById('loginPassword')) document.getElementById('loginPassword').value = rememberedLogin.password || '';
                if (loginRememberMe) loginRememberMe.checked = true;
            }

            openBtns.forEach((btn) => btn.addEventListener('click', openAuthModal));
            document.querySelectorAll('[data-close-auth="true"]').forEach((el) => el.addEventListener('click', closeAuthModal));
            document.querySelectorAll('[data-close-agreement="true"]').forEach((el) => el.addEventListener('click', closeAgreementModal));
            document.querySelectorAll('[data-close-announcement="true"]').forEach((el) => el.addEventListener('click', closeAnnouncementModal));
            document.querySelectorAll('[data-agreement-open]').forEach((el) => {
                el.addEventListener('click', () => openAgreementModal(el.getAttribute('data-agreement-open') || 'user'));
            });
            document.getElementById('announcementPrevBtn')?.addEventListener('click', () => stepAnnouncement(-1));
            document.getElementById('announcementNextBtn')?.addEventListener('click', () => stepAnnouncement(1));
            document.getElementById('announcementSuppressToday')?.addEventListener('change', toggleAnnouncementTodaySuppressed);
            document.querySelectorAll('[data-auth-switch]').forEach((el) => {
                el.addEventListener('click', () => {
                    const target = el.getAttribute('data-auth-switch');
                    if (target === 'register') {
                        loginForm.style.display = 'none';
                        registerForm.style.display = 'flex';
                    } else {
                        loginForm.style.display = 'flex';
                        registerForm.style.display = 'none';
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
                if (!loginAgreementCheck?.checked) {
                    setAuthMessage('请先勾选同意用户协议和隐私协议');
                    return;
                }
                const res = await fetch('/api/auth/login', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({username: account, password, accepted_agreements: true})
                });
                const data = await res.json();
                if (data.ok) {
                    saveRememberedLogin(Boolean(loginRememberMe?.checked), account, password);
                    setToken(data.token, {persist: Boolean(loginRememberMe?.checked)});
                    setAuthMessage('登录成功', false);
                    updateUserPanel(data.user);
                    await initSettingsWorkspace();
                    await Promise.all([loadAiProviders(), loadAiKeys()]);
                    closeAuthModal();
                    discoverDrafts();
                    loadAssistantLogs();
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
                if (!registerAgreementCheck?.checked) {
                    setAuthMessage('请先勾选同意用户协议和隐私协议');
                    return;
                }
                const deviceIdentity = await getDeviceFingerprintPayload();
                const res = await fetch('/api/auth/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        username,
                        password,
                        ref_code: refCode,
                        auto_login: true,
                        device_fingerprint: deviceIdentity.fingerprint,
                        accepted_agreements: true
                    })
                });
                const data = await res.json();
                if (data.ok) {
                    setToken(data.token || '', {persist: false});
                    setAuthMessage(data.message || '注册成功', false);
                    updateUserPanel(data.user);
                    await initSettingsWorkspace();
                    await Promise.all([loadAiProviders(), loadAiKeys()]);
                    closeAuthModal();
                    discoverDrafts();
                    loadAssistantLogs();
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
            const filePath = await requestBrowseFile();
            if (filePath) {
                document.getElementById('split_source_path').value = filePath;
            }
        }

        async function selectSplitSourceFolder() {
            const folder = await requestBrowseFolder();
            if (folder) {
                document.getElementById('split_source_path').value = folder;
            }
        }

        async function selectSplitOutput() {
            const folder = await requestBrowseFolder();
            if (folder) {
                document.getElementById('split_output_dir').value = folder;
            }
        }

        async function selectSplitOutputFolder() {
            await selectSplitOutput();
        }

        async function selectSplitSubtitle() {
            const filePath = await requestBrowseFile();
            if (filePath) {
                document.getElementById('split_subtitle_path').value = filePath;
            }
        }

        async function selectSplitSubtitleFile() {
            await selectSplitSubtitle();
        }

        async function selectSettingsDraftRoot() {
            const folder = await requestBrowseFolder();
            if (folder) {
                const input = document.getElementById('settingsDraftRoot');
                if (input) input.value = folder;
            }
        }

        async function selectExportFolder() {
            const folder = await requestBrowseFolder();
            if (folder) {
                const input = document.getElementById('export_dir');
                if (input) input.value = folder;
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
            const fallbackSettings = {
                workspace: getWorkspaceSettings() || {},
                paths: {},
                services: {}
            };
            if (!getToken()) {
                return fallbackSettings;
            }
            const res = await authFetch('/api/workspace/settings');
            const data = await parseJsonResponse(res, '设置加载失败');
            if (!res.ok || data.ok === false) {
                const message = data.error || '设置加载失败';
                if (res.status === 401 && /missing auth token/i.test(message)) {
                    return fallbackSettings;
                }
                throw new Error(message);
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
            const data = await parseJsonResponse(res, '设置保存失败');
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
                if (!getToken()) {
                    if (strategyInput) strategyInput.value = localSettings.strategy || 'simple';
                    if (autoDiscoverInput) autoDiscoverInput.checked = localSettings.auto_discover !== false;
                    if (autoLoadInput) autoLoadInput.checked = !!localSettings.auto_load_last_draft;
                    return;
                }
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
                const data = await parseJsonResponse(res, '批量导出失败');
                if (!res.ok || !data.ok) {
                    throw new Error(data.error || '多草稿导出失败');
                }
                const lines = [
                    `导出目录：${data.output_dir || exportDir}`,
                    `执行结果：成功 ${data.success_count || 0} / 共 ${data.total || exportDraftQueue.length} 个`
                ];
                if (data.success_count > 0) {
                    lines.push(`本次批量导出已扣除 1 次，剩余 ${data.quota?.remaining ?? '-'} 次`);
                }
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
                setToolResult('export_result', '请先读取已选草稿，再导出主视频片段。');
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
                const data = await parseJsonResponse(res, '主视频片段导出失败');
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
                setToolResult('split_draft_result', '请先读取已选草稿。');
                return;
            }
            setToolResult('split_draft_result', '正在查看已选草稿的内容结构...');
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
            setToolResult('split_multi_result', '正在批量查看草稿结构...');
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
                const lines = [`共 ${data.items?.length || 0} 个草稿：`];
                (data.items || []).forEach((item) => {
                    if (item.ok) {
                        lines.push(`${item.draft_name} | 视频 ${item.video_track_count || 0} | 字幕 ${item.text_track_count || 0} | 主片段 ${item.main_track_segments || 0}`);
                    } else {
                        lines.push(`${item.draft_name} | 读取失败：${item.error || '未知错误'}`);
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
                setToolResult('split_draft_result', '请先读取已选草稿。');
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
                const folder = await requestBrowseFolder();
                if (folder) {
                    const input = document.getElementById('split_draft_output_dir');
                    if (input) input.value = folder;
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
                const summary = getDraftElement('summary', shell);
                if (summary && !summary.dataset.refined) {
                    summary.dataset.refined = 'true';
                    summary.textContent = '最近草稿会显示在下方，选中后会自动带回当前模块。';
                }
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
                button.textContent = '选择草稿';
                button.addEventListener('click', () => openDraftPicker(button.closest('[data-draft-shell="true"]')));
            });
            document.getElementById('draftPickerRefreshBtn')?.addEventListener('click', () => discoverDrafts(activeDraftShell, true, true));
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
            document.getElementById('replace_materials')?.addEventListener('change', syncMixReplaceControls);
            document.getElementById('replace_texts')?.addEventListener('change', syncMixReplaceControls);
            document.getElementById('replace_audios')?.addEventListener('change', syncMixReplaceControls);
            document.querySelectorAll('input[name="replace_type"]').forEach((input) => {
                input.addEventListener('change', syncMixReplaceControls);
            });
            document.getElementById('partition_text_mode')?.addEventListener('change', syncPartitionTextStrategy);
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
                    partition: {kind: 'mix', focusId: 'mix-mode-partition-anchor', mixTarget: 'partition'},
                    sequence: {kind: 'mix', focusId: 'mix-mode-sequence-anchor', mixTarget: 'sequence'}
                }
            },
            ai: {
                panelId: 'panel-ai-make',
                defaultItem: 'make',
                items: {
                    make: {kind: 'panel', panelId: 'panel-ai-make', focusId: 'ai-make-anchor'},
                    inspiration: {kind: 'panel', panelId: 'panel-ai-make', focusId: 'ai-inspiration-anchor'},
                    manga: {kind: 'panel', panelId: 'panel-ai-manga', focusId: 'ai-manga-anchor'}
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
                defaultItem: 'clip-rhythm',
                items: {
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
            assistant: {
                panelId: 'panel-assistant',
                defaultItem: 'assistant-main',
                items: {
                    'assistant-main': {kind: 'panel', panelId: 'panel-assistant'}
                }
            },
            account: {
                panelId: 'panel-account',
                defaultItem: 'account-vip-section',
                items: {
                    'account-profile-section': {kind: 'section', sectionId: 'account-profile-section'},
                    'account-vip-section': {kind: 'section', sectionId: 'account-vip-section'},
                    'account-invite-section': {kind: 'section', sectionId: 'account-invite-section'},
                    'account-license-section': {kind: 'section', sectionId: 'account-license-section'},
                    'account-tutorial-section': {kind: 'section', sectionId: 'account-tutorial-section'},
                    'account-contact-section': {kind: 'section', sectionId: 'account-contact-section'}
                }
            },
            resource: {
                panelId: 'panel-resource-exchange',
                defaultItem: 'resource-square-section',
                items: {
                    'resource-square-section': {kind: 'section', sectionId: 'resource-square-section'},
                    'resource-publish-section': {kind: 'section', sectionId: 'resource-publish-section'}
                }
            }
        };

        let activeWorkspaceNav = {group: 'assistant', item: 'assistant-main'};

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
                if (isActiveGroup) {
                    group.classList.toggle('open', keepOpen);
                } else {
                    group.classList.remove('open');
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
            if (entry.groupKey === 'ai') {
                applyAiWorkspaceSection(entry.itemKey);
            }

            const shouldScroll = options.scroll !== false;
            const scrollTarget = entry.focusId ? document.getElementById(entry.focusId) : targetPanel;
            if (shouldScroll && scrollTarget) {
                scrollTarget.scrollIntoView({behavior: 'smooth', block: 'start'});
            }
        }

        function applyAiWorkspaceSection(itemKey) {
            const aiMakePanel = document.getElementById('panel-ai-make');
            const aiMangaPanel = document.getElementById('panel-ai-manga');
            const aiInspirationCard = document.getElementById('aiInspirationCard');
            if (aiMakePanel) {
                aiMakePanel.querySelectorAll('.tool-card').forEach((node) => {
                    if (!(node instanceof HTMLElement)) return;
                    if (node.id === 'aiInspirationCard') return;
                    node.style.display = itemKey === 'make' ? '' : 'none';
                });
            }
            if (aiInspirationCard) {
                aiInspirationCard.style.display = itemKey === 'inspiration' ? '' : 'none';
            }
            if (aiMangaPanel) {
                aiMangaPanel.style.display = itemKey === 'manga' ? '' : 'none';
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
                if (item.kind === 'panel') {
                    return href === `#${item.panelId || group.panelId}`
                        || (item.focusId && href === `#${item.focusId}`);
                }
                return false;
            });
            if (!matched) return null;
            return {groupKey, itemKey: matched[0]};
        }

        function relocateAiInspirationWorkspace() {
            const aiMenu = document.querySelector('.sidebar-group[data-group="ai"] .sidebar-submenu');
            const clipMenu = document.querySelector('.sidebar-group[data-group="clip"] .sidebar-submenu');
            const clipAiLink = clipMenu?.querySelector('[data-subtab-target="clip-ai"]');
            const mangaLink = document.getElementById('aiMangaSidebarLink');
            if (clipAiLink && aiMenu && !document.getElementById('aiInspirationSidebarLink')) {
                const aiLink = clipAiLink.cloneNode(true);
                aiLink.id = 'aiInspirationSidebarLink';
                aiLink.textContent = 'AI 灵感';
                aiLink.href = '#ai-inspiration-anchor';
                aiLink.removeAttribute('data-subtab-container');
                aiLink.removeAttribute('data-subtab-target');
                if (mangaLink) {
                    aiMenu.insertBefore(aiLink, mangaLink);
                } else {
                    aiMenu.appendChild(aiLink);
                }
                clipAiLink.remove();
            }

            const clipGrid = document.getElementById('clipToolsGrid');
            const aiPanel = document.getElementById('panel-ai-make');
            const aiCard = clipGrid?.querySelector('[data-subtab-group="clip-ai"]');
            if (!aiCard || !aiPanel || document.getElementById('aiInspirationCard')) return;
            const anchor = document.createElement('div');
            anchor.id = 'ai-inspiration-anchor';
            anchor.className = 'anchor-offset';
            aiCard.id = 'aiInspirationCard';
            aiCard.removeAttribute('data-subtab-group');
            aiCard.classList.add('ai-inspiration-card');
            aiCard.style.display = '';
            aiCard.classList.remove('active', 'subtab-panel');
            aiCard.removeAttribute('data-subtab');
            aiCard.removeAttribute('data-subtab-display');
            aiPanel.appendChild(anchor);
            aiPanel.appendChild(aiCard);
        }

        function simplifyExportPanel() {
            ['export_pattern', 'export_cover', 'export_log'].forEach((id) => {
                const group = document.getElementById(id)?.closest('.form-group');
                if (group) group.remove();
            });
        }

        function prepareWorkspaceLayout() {
            relocateAiInspirationWorkspace();
            simplifyExportPanel();
        }

        function reorderAccountSections() {
            const panel = document.getElementById('panel-account');
            const panelBody = document.getElementById('userPanel') || panel;
            const profile = document.getElementById('account-profile-section');
            const vip = document.getElementById('account-vip-section');
            const nav = document.querySelector('.sidebar-group[data-group="account"] .sidebar-submenu');
            const navProfile = nav?.querySelector('[data-hard-section="account-profile-section"]');
            const navVip = nav?.querySelector('[data-hard-section="account-vip-section"]');
            if (
                panelBody
                && profile
                && vip
                && profile.parentElement === panelBody
                && vip.parentElement === panelBody
                && vip.nextElementSibling !== profile
            ) {
                panelBody.insertBefore(vip, profile);
            }
            if (nav && navProfile && navVip && navVip.nextElementSibling !== navProfile) {
                nav.insertBefore(navVip, navProfile);
            }
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
                const folder = await requestBrowseFolder();
                if (!folder) return;
                const input = document.getElementById(inputId);
                if (input) input.value = folder;
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
            const nav = options.hideNav ? null : document.createElement('div');
            if (nav) {
                nav.className = 'subtabs';
                nav.dataset.tabHost = root.id || panelId;
            }
            items.forEach((item, index) => {
                if (nav) {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = `subtab-btn${index === 0 ? ' active' : ''}`;
                    button.textContent = item.label;
                    button.dataset.target = item.id;
                    nav.appendChild(button);
                }

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
            if (nav) {
                root.insertBefore(nav, insertTarget);
                nav.querySelectorAll('.subtab-btn').forEach((button) => {
                    button.addEventListener('click', () => {
                        activateSecondaryTab(root.id || panelId, button.dataset.target);
                    });
                });
            }
            const activeItem = activeWorkspaceNav?.group ? getWorkspaceNavItem(activeWorkspaceNav.group, activeWorkspaceNav.item) : null;
            if (activeItem?.kind === 'subtab' && (activeItem.containerId || activeItem.panelId) === (root.id || panelId)) {
                activateSecondaryTab(root.id || panelId, activeItem.target);
                return;
            }
            activateDefaultSecondaryTab(root.id || panelId, {syncNav: false});
        }

        function activateSecondaryTab(containerId, target, options = {}) {
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
            if (matchedEntry && options.syncNav !== false) {
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

        function activateDefaultSecondaryTab(containerId, options = {}) {
            const root = document.getElementById(containerId);
            if (!root) return;
            const nav = getDirectSubtabs(root);
            const first = nav?.querySelector('.subtab-btn');
            if (!first?.dataset?.target) return;
            activateSecondaryTab(containerId, first.dataset.target, options);
        }

        function activateHardSection(panelId, sectionId) {
            if (!panelId) return;
            const panel = document.getElementById(panelId);
            if (!panel) return;
            panel.querySelectorAll('.hard-section').forEach((node) => {
                node.style.display = node.id === sectionId ? '' : 'none';
            });
            if (panelId === 'panel-account' && sectionId === 'account-vip-section' && getToken()) {
                loadLicenseCardTypes();
            }
            if (panelId === 'panel-account' && sectionId === 'account-contact-section') {
                loadSiteSettings().catch(() => {});
            }
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
                    if (group.classList.contains('active') && group.classList.contains('open')) {
                        group.classList.remove('open');
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
            activateHardSection('panel-account', 'account-vip-section');
            activateHardSection('panel-resource-exchange', 'resource-square-section');
            activateHardSection('panel-settings', 'settings-basic-section');
            applyWorkspaceNavigation('assistant', 'assistant-main', {openActiveGroup: true, scroll: false});
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
            loadDuoCategories();
            renderDuoLists();
            toggleDuoFields();
            if (runtimeFeatures.duo) {
                loadDuoCacheStatus();
                loadFfmpegStatus();
                document.getElementById('duo_param_blur')?.addEventListener('change', syncDuoParamUI);
                document.getElementById('duo_param_shake')?.addEventListener('change', syncDuoParamUI);
                document.getElementById('duo_param_beauty')?.addEventListener('change', syncDuoParamUI);
            }
        }

        function initAssistantWorkspace() {
            document.getElementById('assistantPreviewBtn')?.addEventListener('click', previewAssistantCommand);
            document.getElementById('assistantExecuteBtn')?.addEventListener('click', executeAssistantCommand);
            document.getElementById('assistantRefreshLogsBtn')?.addEventListener('click', loadAssistantLogs);
            loadAssistantLogs();
        }

        function buildTutorialSearchQuery() {
            return (document.getElementById('accountTutorialSearch')?.value || '').trim().toLowerCase();
        }

        function renderAccountTutorial() {
            const box = document.getElementById('accountTutorialList');
            if (!box) return;
            const query = buildTutorialSearchQuery();
            const items = ACCOUNT_TUTORIAL_ENTRIES.filter((item) => {
                if (!query) return true;
                return `${item.title} ${item.keywords} ${item.body}`.toLowerCase().includes(query);
            });
            box.innerHTML = items.length
                ? items.map((item) => `<article class="tutorial-card"><h4>${escapeHtml(item.title)}</h4><p>${escapeHtml(item.body)}</p><div class="tutorial-keywords">${escapeHtml(item.keywords)}</div></article>`).join('')
                : '<div class="tool-result">没有找到匹配的教程关键词。</div>';
        }

        function initAccountTutorial() {
            const input = document.getElementById('accountTutorialSearch');
            if (input && !input.dataset.boundTutorial) {
                input.addEventListener('input', renderAccountTutorial);
                input.dataset.boundTutorial = '1';
            }
            renderAccountTutorial();
        }

        function formatResourceExchangeStatus(status) {
            const mapping = {
                approved: '已通过',
                rejected: '已拒绝',
                pending: '待审核'
            };
            return mapping[status] || status || '待审核';
        }

        function renderResourceExchangeList(items = []) {
            const box = document.getElementById('resourceExchangeList');
            const pager = document.getElementById('resourceExchangePagerInfo');
            const prevBtn = document.getElementById('resourceExchangePrevBtn');
            const nextBtn = document.getElementById('resourceExchangeNextBtn');
            if (!box) return;
            box.innerHTML = items.length
                ? `<div class="resource-table-shell">
                    <div class="resource-table-head">
                        <span>会员等级</span>
                        <span>项目名称</span>
                        <span>项目介绍</span>
                        <span>联系方式</span>
                        <span>发布时间</span>
                    </div>
                    ${items.map((item) => `<article class="resource-table-row">
                        <div class="resource-table-cell"><span class="resource-level-badge">${escapeHtml(item.membership_label || '试用用户')}</span></div>
                        <div class="resource-table-cell"><strong>${escapeHtml(item.project_name || '-')}</strong></div>
                        <div class="resource-table-cell"><span>${escapeHtml(item.project_intro || '-')}</span></div>
                        <div class="resource-table-cell"><span>${escapeHtml(item.contact || '-')}</span></div>
                        <div class="resource-table-cell"><time>${escapeHtml(item.published_at ? new Date(item.published_at).toLocaleString() : '-')}</time></div>
                    </article>`).join('')}
                </div>`
                : '<div class="tool-result">当前还没有通过审核的资源互换内容。</div>';
            if (pager) pager.textContent = `第 ${resourceExchangeState.page} / ${resourceExchangeState.pages} 页，共 ${resourceExchangeState.total} 条`;
            if (prevBtn) prevBtn.disabled = resourceExchangeState.page <= 1;
            if (nextBtn) nextBtn.disabled = resourceExchangeState.page >= resourceExchangeState.pages;
        }

        function renderResourceMyPosts(items = []) {
            const box = document.getElementById('resourceMyPostsList');
            if (!box) return;
            box.innerHTML = items.length
                ? `<div class="resource-table-shell">
                    <div class="resource-table-head resource-table-head-owned">
                        <span>状态</span>
                        <span>项目名称</span>
                        <span>项目介绍</span>
                        <span>联系方式</span>
                        <span>发布时间</span>
                        <span>备注</span>
                    </div>
                    ${items.map((item) => `<article class="resource-table-row resource-table-row-owned">
                        <div class="resource-table-cell"><span class="resource-post-status ${escapeHtml(item.status || 'pending')}">${escapeHtml(formatResourceExchangeStatus(item.status))}</span></div>
                        <div class="resource-table-cell"><strong>${escapeHtml(item.project_name || '-')}</strong></div>
                        <div class="resource-table-cell"><span>${escapeHtml(item.project_intro || '-')}</span></div>
                        <div class="resource-table-cell"><span>${escapeHtml(item.contact || '-')}</span></div>
                        <div class="resource-table-cell"><div>${escapeHtml(item.created_at ? new Date(item.created_at).toLocaleString() : '-')}</div></div>
                        <div class="resource-table-cell"><div class="resource-inline-note">${item.status === 'rejected' ? `拒绝原因：${escapeHtml(item.review_reason || '管理员未填写')}` : (item.status === 'approved' ? '审核已通过，内容已在资源大厅展示。' : '等待管理员审核通过后展示。')}</div></div>
                    </article>`).join('')}
                </div>`
                : '<div class="tool-result">你今天还没有发布资源互换内容。</div>';
        }

        async function loadResourceExchangeList(page = resourceExchangeState.page || 1) {
            const safePage = Math.max(1, Number(page) || 1);
            const res = await fetch(`/api/resource-exchange/list?page=${safePage}`);
            const data = await res.json();
            if (!res.ok || data.ok === false) {
                const box = document.getElementById('resourceExchangeList');
                if (box) box.innerHTML = `<div class="tool-result">${escapeHtml(data.error || '资源互换列表加载失败')}</div>`;
                return;
            }
            const pagination = data.pagination || {};
            resourceExchangeState.page = pagination.page || safePage;
            resourceExchangeState.pages = pagination.pages || 1;
            resourceExchangeState.total = pagination.total || 0;
            resourceExchangeState.items = Array.isArray(data.items) ? data.items : [];
            renderResourceExchangeList(resourceExchangeState.items);
        }

        async function loadResourceExchangeMyPosts() {
            const box = document.getElementById('resourceMyPostsList');
            if (!getToken()) {
                if (box) box.innerHTML = '<div class="tool-result">登录后查看自己的发布记录。</div>';
                return;
            }
            const res = await authFetch('/api/resource-exchange/my-posts');
            const data = await res.json();
            if (!res.ok || data.ok === false) {
                if (box) box.innerHTML = `<div class="tool-result">${escapeHtml(data.error || '发布记录加载失败')}</div>`;
                return;
            }
            resourceExchangeState.myPosts = Array.isArray(data.items) ? data.items : [];
            renderResourceMyPosts(resourceExchangeState.myPosts);
        }

        async function publishResourceExchange() {
            const statusEl = document.getElementById('resourcePublishStatus');
            if (!getToken()) {
                if (statusEl) statusEl.textContent = '请先登录后再发布。';
                return;
            }
            const payload = {
                project_name: document.getElementById('resourceProjectName')?.value?.trim() || '',
                project_intro: document.getElementById('resourceProjectIntro')?.value?.trim() || '',
                contact: document.getElementById('resourceContact')?.value?.trim() || ''
            };
            if (statusEl) statusEl.textContent = '正在提交...';
            const res = await authFetch('/api/resource-exchange/publish', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            const data = await res.json();
            if (!res.ok || data.ok === false) {
                if (statusEl) statusEl.textContent = data.error || '发布失败';
                return;
            }
            if (statusEl) statusEl.textContent = '发布成功，等待管理员审核。';
            if (document.getElementById('resourceProjectName')) document.getElementById('resourceProjectName').value = '';
            if (document.getElementById('resourceProjectIntro')) document.getElementById('resourceProjectIntro').value = '';
            if (document.getElementById('resourceContact')) document.getElementById('resourceContact').value = '';
            notify('资源互换已提交审核', 'success');
            await Promise.all([loadResourceExchangeMyPosts(), loadResourceExchangeList(1)]);
        }

        function fillResourceMembership() {
            const input = document.getElementById('resourcePublishMembership');
            if (!input) return;
            input.value = currentUserInfo?.membership_label || (currentUserInfo?.is_vip ? 'VIP会员' : '试用用户');
        }

        function initResourceExchangeWorkspace() {
            document.getElementById('resourceExchangeRefreshBtn')?.addEventListener('click', () => loadResourceExchangeList(1));
            document.getElementById('resourceExchangePrevBtn')?.addEventListener('click', () => loadResourceExchangeList(resourceExchangeState.page - 1));
            document.getElementById('resourceExchangeNextBtn')?.addEventListener('click', () => loadResourceExchangeList(resourceExchangeState.page + 1));
            document.getElementById('resourcePublishBtn')?.addEventListener('click', publishResourceExchange);
            document.getElementById('resourceMyPostsRefreshBtn')?.addEventListener('click', loadResourceExchangeMyPosts);
            fillResourceMembership();
            loadResourceExchangeList(1);
            if (getToken()) {
                loadResourceExchangeMyPosts();
            }
        }

        async function initWorkspacePage() {
            initTheme();
            initAuthUI();
            // Desktop flow: require explicit login on each launch to avoid silent stale-session bypass.
            clearToken();
            openAuthModal();
            prepareWorkspaceLayout();
            reorderAccountSections();
            initWorkspaceSidebar();

            try {
                await loadSiteSettings();
            } catch (e) {
                console.warn('loadSiteSettings failed', e);
            }
            try {
                await loadRuntimeFeatures();
            } catch (e) {
                console.warn('loadRuntimeFeatures failed', e);
            }
            try {
                await loadUserInfo();
            } catch (e) {
                console.warn('loadUserInfo failed', e);
            }

            initDraftWorkspace();
            initEffectWorkspace();
            initAssistantWorkspace();
            initResourceExchangeWorkspace();
            initAccountTutorial();
            initSplitWorkspace();
            initSecondaryTabs('panel-split', [
                {id: 'split-file', label: '文件分割', indexes: [0]},
                {id: 'split-draft', label: '草稿处理', indexes: [1, 2]},
                {id: 'split-batch', label: '批量查看', indexes: [3]}
            ], {hideNav: true});
            initSecondaryTabs('panel-effects', [
                {id: 'effects-core', label: '效果配置', indexes: [0, 4]},
                {id: 'effects-resource', label: '资源库', indexes: [1]},
                {id: 'effects-duo', label: 'Duo 资源', indexes: [2, 3, 5, 6]}
            ], {
                hideNav: true,
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
                {id: 'clip-rhythm', label: '节奏变速', indexes: [0]},
                {id: 'clip-transform', label: '画面校正', indexes: [1]},
                {id: 'clip-shake', label: '摇晃关键帧', indexes: [2]}
            ], {rootId: 'clipToolsGrid', hideNav: true});
            initSecondaryTabs('panel-export', [
                {id: 'export-segments', label: '片段导出', indexes: [0, 1]},
                {id: 'export-batch', label: '批量导出', indexes: [2]},
                {id: 'export-settings', label: '导出设置', indexes: [3]}
            ], {hideNav: true});
            initSettingsWorkspace();
            await Promise.all([loadAiProviders(), loadAiKeys()]);
            initAiWorkspace();
            const aiTextStatus = document.getElementById('ai_text_status');
            if (aiTextStatus && aiTextStatus.textContent.includes('选择账号并填写需求后即可开始')) {
                aiTextStatus.textContent = '';
            }
            if (getWorkspaceSettings().auto_discover !== false) {
                discoverDrafts();
            }
            if (!getToken()) {
                openAuthModal();
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            initWorkspacePage().catch((err) => {
                console.error('initWorkspacePage failed', err);
                try {
                    if (!document.querySelector('.sidebar-group.active')) {
                        initWorkspaceSidebar();
                    }
                } catch (e) {}
            });
        });

        async function pollTaskStatus(jobId) {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(async () => {
                try {
                    const response = await authFetch(`/api/task/${jobId}`);
                    const data = await response.json();
                    if (!response.ok) throw new Error(data.error || '查询失败');

                    const progress = data.progress || {};
                    const progressInfo = progress && typeof progress === 'object' ? progress : {};
                    let percent = 0;
                    if (typeof progress === 'number') {
                        percent = progress;
                    } else if (typeof progressInfo.progress === 'number') {
                        percent = progressInfo.progress;
                    } else if (typeof progressInfo.progress === 'string') {
                        percent = parseFloat(progressInfo.progress) || 0;
                    }
                    const progressLabel = progressInfo.indication
                        || (typeof progressInfo.progress === 'string' ? progressInfo.progress : '')
                        || '处理中...';
                    document.getElementById('progress-fill').style.width = `${percent}%`;
                    document.getElementById('progress-text').innerText = progressLabel;

                    if (data.status === 'finished') {
                        clearInterval(pollInterval);
                        pollInterval = null;
                        document.getElementById('progress-text').innerText = '✅ 生成完成！';
                        const taskResult = progressInfo.result && typeof progressInfo.result === 'object' ? progressInfo.result : {};
                        notify('批量生成已完成，请直接查看本批新草稿。', 'success');
                        document.getElementById('submitBtn').disabled = false;
                        let draftsFolder = '';
                        try {
                            const folderResponse = await fetch('/api/drafts-folder');
                            const folderData = await folderResponse.json();
                            draftsFolder = folderData.folder || '';
                            if (draftsFolder) {
                                document.getElementById('progress-text').innerHTML += `<br>📂 草稿已保存至：${escapeHtml(draftsFolder)}`;
                            }
                        } catch (folderError) {
                            console.warn('load drafts folder failed', folderError);
                        }
                        renderMixGenerationResult(taskResult, {draftsFolder});
                        await Promise.all([
                            loadUserInfo(),
                            discoverDrafts().catch((discoverError) => {
                                console.warn('discoverDrafts after batch failed', discoverError);
                            })
                        ]);
                    } else if (data.status === 'failed') {
                        clearInterval(pollInterval);
                        pollInterval = null;
                        document.getElementById('progress-text').innerText = `❌ 生成失败: ${data.error_msg || '未知错误'}`;
                        notify(data.error_msg || '生成失败，请检查当前设置。', 'error');
                        document.getElementById('submitBtn').disabled = false;
                        await loadUserInfo();
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

function renderAssistantPreview(data = null) {
    const box = document.getElementById('assistantPreviewBox');
    if (!box) return;
    if (!data) {
        box.innerHTML = '<div class="assistant-preview-card"><strong>输入一句需求后，这里会显示推荐动作、会影响哪些内容，以及是否需要确认。</strong><span>例如：帮我创建素材目录、切到槽位拼接混剪、导出当前草稿。</span></div>';
        return;
    }
    if (!data.ok) {
        box.innerHTML = `<div class="assistant-preview-card assistant-preview-warning"><strong>暂时无法处理这条命令</strong><span>${escapeHtml(data.error || '命令预览失败。')}</span></div>`;
        return;
    }
    const action = data.client_action || {};
    const meta = [
        `<span class="assistant-preview-chip">${data.requires_confirmation ? '执行前需要确认' : '可直接执行'}</span>`,
        `<span class="assistant-preview-chip">${escapeHtml(describeAssistantClientAction(action))}</span>`
    ];
    if (Array.isArray(data.missing) && data.missing.length) {
        meta.push(`<span class="assistant-preview-chip assistant-preview-chip-warn">还缺：${escapeHtml(data.missing.join('、'))}</span>`);
    }
    box.innerHTML = `
        <article class="assistant-preview-card">
            <div class="assistant-preview-label">推荐操作</div>
            <h4>${escapeHtml(data.summary || '未识别动作')}</h4>
            <p>${escapeHtml(data.impact || '本次操作不会修改草稿之外的内容。')}</p>
            <div class="assistant-preview-meta">${meta.join('')}</div>
        </article>
    `;
}

function renderAssistantLogs(items = []) {
    const box = document.getElementById('assistantLogList');
    if (!box) return;
    if (!items.length) {
        box.innerHTML = '<div class="tool-result">登录后可以查看最近的助手记录。</div>';
        return;
    }
    box.innerHTML = `
        <div class="resource-table-shell assistant-log-table">
            <div class="resource-table-head">
                <span>状态</span>
                <span>时间</span>
                <span>内容</span>
            </div>
            ${items.map((item) => {
                const payload = item.payload || {};
                const summary = payload.command || payload.summary || payload.response?.summary || '-';
                const timeText = item.created_at ? new Date(item.created_at).toLocaleString() : '-';
                return `
                    <article class="resource-table-row">
                        <div class="resource-table-cell"><span class="resource-level-badge">${escapeHtml(formatAssistantStageLabel(item.stage || '-'))}</span></div>
                        <div class="resource-table-cell"><span>${escapeHtml(timeText)}</span></div>
                        <div class="resource-table-cell assistant-log-summary"><div><strong>${escapeHtml(summary)}</strong><span>${escapeHtml(describeAssistantClientAction(payload.response?.client_action || payload.client_action || {}))}</span></div></div>
                    </article>
                `;
            }).join('')}
        </div>
    `;
}

function formatAssistantStageLabel(stage) {
    const mapping = {
        preview: '已预览',
        execute: '已执行',
        error: '异常',
        materials_fill_folder: '放素材',
        materials_layout: '创建目录',
        create_material_layout: '创建目录',
        material_layout_created: '目录已创建',
        fill_text_template: '文字模板'
    };
    return mapping[stage] || stage || '记录';
}

function describeAssistantClientAction(action = {}) {
    if (!action || typeof action !== 'object') return '等待进一步识别';
    if (action.type === 'navigate') return '会自动跳转到对应功能页';
    if (action.type === 'material_layout_created') return '会直接创建素材目录';
    if (action.type === 'fill_text_template') return '会自动填充文字模板';
    return '会调用当前工作台已有能力';
}

async function loadAssistantLogs() {
    if (!getToken()) {
        renderAssistantLogs([]);
        return;
    }
    try {
        const res = await authFetch('/api/assistant/logs?limit=12');
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || '日志读取失败');
        renderAssistantLogs(data.items || []);
    } catch (e) {
        renderAssistantLogs([{stage: 'error', created_at: new Date().toISOString(), payload: {command: e.message || String(e)}}]);
    }
}

function applyAssistantClientAction(action = {}) {
    if (!action || typeof action !== 'object') return;
    if (action.type === 'navigate') {
        if (action.mix_target) {
            applyWorkspaceNavigation('mix', action.mix_target, {openActiveGroup: true});
            return;
        }
        if (action.subtab_target && action.panel_id === 'panel-export') {
            applyWorkspaceNavigation('export', action.subtab_target, {openActiveGroup: true});
            return;
        }
        if (action.subtab_target && action.panel_id === 'panel-split') {
            applyWorkspaceNavigation('split', action.subtab_target, {openActiveGroup: true});
            return;
        }
        if (action.section_id && action.section_id.startsWith('settings-')) {
            openWorkspaceSettingsSection(action.section_id);
            return;
        }
        if (action.section_id && action.section_id.startsWith('account-')) {
            showWorkspacePanel('panel-account');
            activateHardSection('panel-account', action.section_id);
            return;
        }
        if (action.panel_id) {
            showWorkspacePanel(action.panel_id, action.anchor || '');
        }
        return;
    }
    if (action.type === 'material_layout_created') {
        const layout = action.layout || {};
        if (layout.root && document.getElementById('folder_path')) {
            document.getElementById('folder_path').value = layout.root;
            updatePrimaryActionState();
        }
        const status = document.getElementById('materialLayoutStatus');
        if (status && layout.root) {
            status.textContent = `已创建：${layout.root}`;
        }
        return;
    }
    if (action.type === 'fill_text_template') {
        const lines = Array.isArray(action.lines) ? action.lines : [];
        const box = document.getElementById('text_batch_input');
        if (box) box.value = lines.join('\n');
        fillTextInputsFromLines(lines);
    }
}

async function previewAssistantCommand() {
    const input = document.getElementById('assistantCommandInput');
    const command = input?.value?.trim() || '';
    if (!command) {
        renderAssistantPreview({ok: false, error: '请输入要执行的命令。'});
        return;
    }
    try {
        const res = await authFetch('/api/assistant/command/preview', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({command, context: buildAssistantContext()})
        });
        const data = await res.json();
        assistantPreviewState = data;
        renderAssistantPreview(data);
        await loadAssistantLogs();
    } catch (e) {
        assistantPreviewState = null;
        renderAssistantPreview({ok: false, error: e.message || String(e)});
    }
}

async function executeAssistantCommand() {
    const command = document.getElementById('assistantCommandInput')?.value?.trim() || '';
    if (!command) {
        renderAssistantPreview({ok: false, error: '请输入要执行的命令。'});
        return;
    }
    const preview = assistantPreviewState && assistantPreviewState.ok ? assistantPreviewState : null;
    if (!preview) {
        await previewAssistantCommand();
        if (!assistantPreviewState?.ok) return;
    }
    const requiresConfirmation = !!assistantPreviewState?.requires_confirmation;
    if (requiresConfirmation) {
        const ok = await confirmAction(`${assistantPreviewState.summary || '确认执行'}\n${assistantPreviewState.impact || ''}`);
        if (!ok) return;
    }
    try {
        const res = await authFetch('/api/assistant/command/execute', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                command,
                context: buildAssistantContext(),
                confirmed: true
            })
        });
        const data = await res.json();
        if (!res.ok || !data.ok) throw new Error(data.error || '执行失败');
        renderAssistantPreview({
            ok: true,
            summary: data.summary,
            impact: data.impact,
            requires_confirmation: false,
            client_action: data.client_action || {}
        });
        applyAssistantClientAction(data.client_action || {});
        await loadAssistantLogs();
    } catch (e) {
        renderAssistantPreview({ok: false, error: e.message || String(e)});
    }
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
        mapAiKeyOptions('storyboard_text_key', 'openai');
        mapAiKeyOptions('storyboard_image_key', 'openai');
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
    mapAiKeyOptions('storyboard_text_key', 'openai');
    mapAiKeyOptions('storyboard_image_key', 'openai');
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
        document.getElementById('ai_jimeng_status').textContent = '请先到“软件设置 → AI账号管理”准备默认可用账号，再填写提示词。';
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
        document.getElementById('ai_volc_status').textContent = '请先到“软件设置 → AI账号管理”准备默认可用账号，再把参数填写完整。';
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
        document.getElementById('ai_text_status').textContent = '请先到“软件设置 → AI账号管理”准备默认可用账号，再填写文案需求。';
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
    const firstInput = document.querySelector('#texts_area textarea[id^="text_"], #texts_area input[type="text"]');
    if (firstInput) firstInput.value = text;
}

const STORYBOARD_SHOT_TYPE_LABELS = {
    scene: '场景镜头',
    character: '人物镜头',
    dialogue: '对白镜头',
    action: '动作镜头'
};

function normalizeStoryboardCharacters(value) {
    const raw = Array.isArray(value) ? value.join('、') : String(value || '');
    const parts = raw
        .split(/[\n,，、\/|；;]+/)
        .map((item) => item.trim())
        .filter(Boolean);
    return Array.from(new Set(parts));
}

function cleanupStoryboardText(value) {
    return String(value || '').replace(/\r/g, '').replace(/\u3000/g, ' ').trim();
}

function detectStoryboardShotType(value, fallbackText = '') {
    const raw = `${value || ''} ${fallbackText || ''}`.toLowerCase();
    if (/dialogue|对白|对话|说话|开口|回答|问道|说道|问她|问他|“|”|"|'/.test(raw)) return 'dialogue';
    if (/action|动作|奔跑|冲向|推开|拿起|转身|抬头|挥手|走向|扑向|打斗|拥抱/.test(raw)) return 'action';
    if (/character|人物|特写|近景|半身|正脸|肖像/.test(raw)) return 'character';
    return 'scene';
}

function normalizeStoryboardItem(item, index) {
    const scene = cleanupStoryboardText(item?.scene || item?.summary || item?.description || '');
    const dialogue = cleanupStoryboardText(item?.dialogue || item?.quoted_dialogue || item?.subtitle || '');
    const visualAction = cleanupStoryboardText(item?.visual_action || item?.action || '');
    const setting = cleanupStoryboardText(item?.setting || item?.location || '');
    const camera = cleanupStoryboardText(item?.camera || item?.shot || '');
    const emotion = cleanupStoryboardText(item?.emotion || '');
    const speaker = cleanupStoryboardText(item?.speaker || '');
    const characters = normalizeStoryboardCharacters(item?.characters || speaker);
    const shotType = detectStoryboardShotType(item?.shot_type || item?.type || '', `${scene} ${dialogue} ${visualAction} ${camera}`);
    const imagePromptText = cleanupStoryboardText(item?.image_prompt_text || [
        characters.length ? `人物：${characters.join('、')}` : '',
        setting ? `场景：${setting}` : '',
        scene ? `画面：${scene}` : '',
        visualAction ? `动作：${visualAction}` : '',
        emotion ? `情绪：${emotion}` : '',
        camera ? `镜头：${camera}` : '',
        dialogue ? '保留说话状态和对白氛围，不要做成纯风景。' : ''
    ].filter(Boolean).join('，'));
    return {
        index: Number(item?.index || index || 1),
        scene,
        dialogue,
        visual_action: visualAction,
        setting,
        camera,
        emotion,
        speaker,
        characters,
        shot_type: shotType,
        image_prompt_text: imagePromptText
    };
}

function extractJsonBlock(raw) {
    const text = String(raw || '').trim();
    if (!text) return '';
    const fenceMatch = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
    if (fenceMatch && fenceMatch[1]) return fenceMatch[1].trim();
    return text;
}

function parseStoryboardItemsFromText(rawText) {
    const text = extractJsonBlock(rawText);
    if (!text) return [];
    const tryParse = (payload) => {
        if (Array.isArray(payload)) return payload;
        if (payload && typeof payload === 'object') {
            if (Array.isArray(payload.items)) return payload.items;
            if (Array.isArray(payload.shots)) return payload.shots;
            if (Array.isArray(payload.storyboard)) return payload.storyboard;
        }
        return null;
    };
    try {
        const parsed = JSON.parse(text);
        const items = tryParse(parsed);
        if (items) return items.map((item, idx) => normalizeStoryboardItem(item, idx + 1)).filter((item) => item.scene || item.dialogue || item.visual_action || item.setting);
    } catch (e) {
        // ignore and use fallback parsing below
    }
    return text
        .split(/\n{2,}/)
        .map((chunk) => cleanupStoryboardText(chunk))
        .filter(Boolean)
        .map((chunk, idx) => normalizeStoryboardItem({dialogue: chunk, scene: chunk}, idx + 1));
}

function formatStoryboardTime(seconds) {
    const totalMs = Math.max(0, Math.round(Number(seconds || 0) * 1000));
    const ms = totalMs % 1000;
    const totalSeconds = Math.floor(totalMs / 1000);
    const sec = totalSeconds % 60;
    const totalMinutes = Math.floor(totalSeconds / 60);
    const min = totalMinutes % 60;
    const hour = Math.floor(totalMinutes / 60);
    return `${String(hour).padStart(2, '0')}:${String(min).padStart(2, '0')}:${String(sec).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

function buildStoryboardSrtText(items, durationSeconds = 3) {
    let cursor = 0;
    return items.map((entry, idx) => {
        const item = normalizeStoryboardItem(entry, idx + 1);
        const duration = Math.max(1, Number(durationSeconds || 3));
        const start = formatStoryboardTime(cursor);
        const end = formatStoryboardTime(cursor + duration);
        cursor += duration;
        const text = cleanupStoryboardText(item.dialogue || item.scene || item.visual_action || item.setting || `镜头 ${idx + 1}`);
        return `${idx + 1}\n${start} --> ${end}\n${text}`;
    }).join('\n\n');
}

function renderStoryboardSentenceList(items) {
    const box = document.getElementById('storyboard_sentence_list');
    if (!box) return;
    if (!Array.isArray(items) || !items.length) {
        box.innerHTML = '<div class="tool-result">生成 SRT 后，这里会按条显示分镜卡片。</div>';
        return;
    }
    box.innerHTML = items.map((entry, idx) => {
        const item = normalizeStoryboardItem(entry, idx + 1);
        const meta = [
            item.setting ? `场景：${item.setting}` : '',
            item.camera ? `镜头：${item.camera}` : '',
            item.emotion ? `情绪：${item.emotion}` : '',
            item.speaker ? `说话人：${item.speaker}` : ''
        ].filter(Boolean).join(' ｜ ');
        const characterTags = item.characters.map((name) => `<span class="storyboard-character-badge">${escapeHtml(name)}</span>`).join('');
        return `
            <article class="storyboard-sentence-card">
                <div class="storyboard-sentence-head">
                    <strong>镜头 ${item.index || idx + 1}</strong>
                    <span class="storyboard-shot-badge">${escapeHtml(STORYBOARD_SHOT_TYPE_LABELS[item.shot_type] || STORYBOARD_SHOT_TYPE_LABELS.scene)}</span>
                </div>
                <div class="storyboard-sentence-text">${escapeHtml(item.dialogue || item.scene || item.visual_action || '暂无文本')}</div>
                ${item.scene && item.scene !== item.dialogue ? `<div class="storyboard-sentence-text">画面：${escapeHtml(item.scene)}</div>` : ''}
                ${item.visual_action ? `<div class="storyboard-sentence-text">动作：${escapeHtml(item.visual_action)}</div>` : ''}
                ${meta ? `<div class="storyboard-sentence-text">${escapeHtml(meta)}</div>` : ''}
                ${characterTags ? `<div class="storyboard-sentence-meta">${characterTags}</div>` : ''}
                <div class="storyboard-sentence-actions">
                    <button class="effect-add" type="button" onclick="useStoryboardSentenceForImage(${item.index || idx + 1})">用于生图</button>
                </div>
            </article>
        `;
    }).join('');
}

function buildStoryboardPrompt(sourceText, durationSeconds) {
    return [
        '请把下面文案整理成适合短视频漫剧的结构化分镜。',
        '只返回 JSON，不要解释，不要 Markdown 代码块。',
        '返回格式：{"items":[{"index":1,"scene":"","dialogue":"","visual_action":"","setting":"","camera":"","emotion":"","speaker":"","characters":[],"shot_type":"scene"}]}',
        'shot_type 只能是：scene、character、dialogue、action。',
        `默认每条字幕时长大约 ${Number(durationSeconds || 3)} 秒，但你不需要输出时间轴。`,
        '要求：对白镜头要尽量保留说话人；有人物时把人物名放进 characters；画面描述只写能看见的内容。',
        '',
        sourceText
    ].join('\n');
}

function setStoryboardImagePrompt(value, item = null) {
    const input = document.getElementById('ai_storyboard_image_prompt');
    if (!input) return;
    input.value = value || '';
    if (item && typeof item === 'object') {
        input.dataset.storyboardItem = JSON.stringify(item);
        input.dataset.storyboardImagePrompt = value || '';
    } else {
        delete input.dataset.storyboardItem;
        delete input.dataset.storyboardImagePrompt;
    }
}

function useStoryboardSentenceForImage(index) {
    const target = Number(index || 0);
    const item = storyboardItemsCache.find((entry) => Number(entry.index || 0) === target);
    if (!item) return;
    setStoryboardImagePrompt(item.image_prompt_text || item.scene || item.dialogue || '', item);
    document.getElementById('ai_storyboard_image_status').textContent = `已带入镜头 ${target} 的生图提示词。`;
}

async function pollAiTaskUntilDone(taskId, statusEl) {
    const target = typeof statusEl === 'string' ? document.getElementById(statusEl) : statusEl;
    for (let count = 0; count < 120; count += 1) {
        const res = await authFetch(`/api/ai/task/${taskId}`);
        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.error || '查询失败');
        const task = data.task || {};
        if (task.status === 'success') {
            if (target) target.textContent = '生成完成';
            return task;
        }
        if (task.status === 'failed') {
            throw new Error(task.error_msg || '执行失败');
        }
        if (target) target.textContent = `正在生成分镜... ${count + 1}`;
        await new Promise((resolve) => setTimeout(resolve, 2000));
    }
    throw new Error('任务超时');
}

async function generateStoryboardSrt() {
    const sourceText = cleanupStoryboardText(document.getElementById('storyboard_source_text')?.value || '');
    const keyId = parseInt(document.getElementById('storyboard_text_key')?.value || '0', 10);
    const durationSeconds = parseFloat(document.getElementById('storyboard_duration_seconds')?.value || '3');
    const status = document.getElementById('storyboard_status');
    const result = document.getElementById('storyboard_result');
    if (!keyId || !sourceText) {
        if (status) status.textContent = '请先选择脚本账号并粘贴文案。';
        return;
    }
    if (status) status.textContent = '正在提交分镜任务...';
    if (result) result.value = '';
    storyboardItemsCache = [];
    storyboardSourceTextCache = sourceText;
    renderStoryboardSentenceList([]);
    const res = await authFetch('/api/ai/generate/text', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            key_id: keyId,
            prompt: buildStoryboardPrompt(sourceText, durationSeconds),
            temperature: 0.3,
            max_tokens: 2400
        })
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        if (status) status.textContent = data.error || '分镜提交失败';
        return;
    }
    try {
        const task = await pollAiTaskUntilDone(data.task_id, status);
        const items = parseStoryboardItemsFromText(task.result_text || '');
        if (!items.length) throw new Error('没有解析出可用分镜');
        storyboardItemsCache = items.map((item, idx) => normalizeStoryboardItem(item, idx + 1));
        if (result) result.value = buildStoryboardSrtText(storyboardItemsCache, durationSeconds);
        renderStoryboardSentenceList(storyboardItemsCache);
        if (status) status.textContent = `已生成 ${storyboardItemsCache.length} 条分镜。`;
        if (storyboardItemsCache[0]) useStoryboardSentenceForImage(storyboardItemsCache[0].index);
    } catch (e) {
        if (status) status.textContent = e.message || '生成失败';
    }
}

function downloadStoryboardSrt() {
    const text = document.getElementById('storyboard_result')?.value?.trim() || '';
    const status = document.getElementById('storyboard_status');
    if (!text) {
        if (status) status.textContent = '请先生成 SRT。';
        return;
    }
    const blob = new Blob([text], {type: 'text/plain;charset=utf-8'});
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `storyboard_${new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '')}.srt`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
    if (status) status.textContent = 'SRT 已下载。';
}

async function fetchLatestUserMaterial(type = 'image') {
    const res = await authFetch(`/api/user/materials?type=${encodeURIComponent(type)}`);
    const data = await res.json();
    if (!res.ok || data.ok === false) throw new Error(data.error || '素材列表读取失败');
    return Array.isArray(data.items) ? data.items : [];
}

async function startAiStoryboardImage() {
    const promptInput = document.getElementById('ai_storyboard_image_prompt');
    const keyId = parseInt(document.getElementById('storyboard_image_key')?.value || '0', 10);
    const size = document.getElementById('storyboard_image_size')?.value || '1024x1024';
    const status = document.getElementById('ai_storyboard_image_status');
    const result = document.getElementById('ai_storyboard_image_result');
    const prompt = cleanupStoryboardText(promptInput?.value || '');
    if (!keyId || !prompt) {
        if (status) status.textContent = '请先选择生图账号并准备提示词。';
        return;
    }
    let previousLatestId = 0;
    try {
        const previousItems = await fetchLatestUserMaterial('image');
        previousLatestId = Number(previousItems[0]?.id || 0);
    } catch (e) {
        previousLatestId = 0;
    }
    if (status) status.textContent = '正在生图，请稍候...';
    if (result) result.textContent = '正在生成图片...';
    const res = await authFetch('/api/ai/generate', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            key_id: keyId,
            task_type: 'image',
            prompt,
            size
        })
    });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        if (status) status.textContent = data.error || '生图失败';
        if (result) result.textContent = data.error || '生图失败';
        return;
    }
    try {
        const imageItems = await fetchLatestUserMaterial('image');
        const latest = imageItems.find((item) => Number(item.id || 0) !== previousLatestId) || imageItems[0] || null;
        if (latest && latest.id) {
            const previewUrl = `/api/user/materials/file/${latest.id}`;
            result.innerHTML = `
                <div class="storyboard-sentence-text">已生成图片素材 #${latest.id}</div>
                <div class="storyboard-sentence-text">${escapeHtml(latest.file_path || '')}</div>
                <div style="margin-top:12px;"><img src="${previewUrl}" alt="storyboard image" style="max-width:100%; border-radius:16px;"></div>
                <div class="storyboard-sentence-actions"><a class="effect-add" href="${previewUrl}" target="_blank" rel="noopener">打开预览</a></div>
            `;
        } else {
            result.textContent = data.path || '图片已生成，请到最近 AI 素材查看。';
        }
        if (status) status.textContent = '图片生成完成。';
        await refreshAiMaterials();
    } catch (e) {
        if (status) status.textContent = '图片已生成，但预览读取失败。';
        result.textContent = data.path || e.message || '图片已生成，请到最近 AI 素材查看。';
    }
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
    setMangaUiRunning(true);
    setMangaStatus('正在生成剪映草稿...');
    startMangaProgress();
    mangaAbortController = new AbortController();
    const payload = {
        project_name: document.getElementById('manga_project_name')?.value?.trim() || '',
        script,
        scene_duration: parseFloat(document.getElementById('manga_scene_duration')?.value || '3'),
        aspect: document.getElementById('manga_aspect')?.value || 'portrait'
    };
    try {
        const res = await authFetch('/api/ai/manga/generate-draft', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), signal: mangaAbortController.signal });
        const data = await res.json();
        if (!res.ok || data.ok === false) throw new Error(data.error || '生成失败');
        renderMangaDraftResult(data);
        if (data.quota && currentUserInfo) {
            currentUserInfo = Object.assign({}, currentUserInfo, data.quota);
            updateUserPanel(currentUserInfo);
        } else {
            await loadUserInfo();
        }
        setMangaStatus(data.message || '生成完成');
        await loadMangaHistory();
        await discoverDrafts(getCurrentDraftShell(document.getElementById('panel-materials')), false, true).catch((discoverError) => {
            console.warn('discoverDrafts after manga failed', discoverError);
        });
    } catch (e) {
        setMangaStatus(e.name === 'AbortError' ? '已取消' : (e.message || '生成失败'));
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

function renderMangaDraftResult(result = {}) {
    const box = document.getElementById('mangaDraftResult');
    if (!box) return;
            if (!result || (!result.draft_path && !result.workspace && !result.scenes)) {
                box.innerHTML = '生成成功后，这里会显示剪映草稿、场景目录和分镜摘要。';
                return;
            }
            const workspace = result.workspace || {};
            const scenes = Array.isArray(result.scenes) ? result.scenes : [];
            box.innerHTML = [
        `<div class="manga-result-item"><strong>草稿名称</strong><span class="manga-result-value">${escapeHtml(result.draft_name || '-')}</span></div>`,
        `<div class="manga-result-item"><strong>剪映草稿</strong><span class="manga-result-value">${escapeHtml(result.draft_path || '-')}</span></div>`,
        `<div class="manga-result-item"><strong>场景目录</strong><span class="manga-result-value">${escapeHtml(workspace.materials_root || '-')}</span></div>`,
        `<div class="manga-result-item"><strong>分镜说明</strong><span class="manga-result-value">${escapeHtml(workspace.script_path || '-')}</span></div>`,
        `<div class="manga-result-item"><strong>场景数量 / 总时长</strong><span class="manga-result-value">${escapeHtml(String(result.scene_count || scenes.length || 0))} / ${escapeHtml(String(result.total_duration || 0))} 秒</span></div>`,
        scenes.length ? `<div class="manga-scene-preview">${scenes.slice(0, 6).map((item) => `<span>${escapeHtml(`${item.index}. ${item.text}`)}</span>`).join('')}</div>` : ''
    ].join('');
}

function fillMangaFormFromParams(params = {}, autoRun = false) {
    if (document.getElementById('manga_project_name')) document.getElementById('manga_project_name').value = params.project_name || '';
    if (document.getElementById('manga_script')) document.getElementById('manga_script').value = params.script || '';
    if (document.getElementById('manga_scene_duration') && params.scene_duration) document.getElementById('manga_scene_duration').value = params.scene_duration;
    if (document.getElementById('manga_aspect') && params.aspect) document.getElementById('manga_aspect').value = params.aspect;
    if (!autoRun) setMangaStatus('已带入模板，可直接生成。');
    if (autoRun) startMangaGenerate();
}

async function loadMangaTemplates() {
    const box = document.getElementById('manga_template_list');
    if (!box) return;
    if (!getToken()) {
        box.innerHTML = '登录后可保存自己的脚本模板。';
        return;
    }
    const res = await authFetch('/api/manga/templates');
    const data = await res.json();
    mangaTemplatesCache = Array.isArray(data.items) ? data.items : [];
    box.innerHTML = mangaTemplatesCache.length ? mangaTemplatesCache.map((item) => `<div class="key-item"><div class="key-row"><strong>${escapeHtml(item.name)}</strong><span class="key-badge">${item.usage_count || 0}</span></div><div class="key-actions"><button class="effect-add" type="button" onclick="applyMangaTemplate(${item.id}, false)">填充</button><button class="effect-add" type="button" onclick="applyMangaTemplate(${item.id}, true)">直接生成</button></div></div>`).join('') : '暂无模板';
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
            project_name: document.getElementById('manga_project_name')?.value?.trim() || '',
            script: document.getElementById('manga_script')?.value?.trim() || '',
            scene_duration: parseFloat(document.getElementById('manga_scene_duration')?.value || '3'),
            aspect: document.getElementById('manga_aspect')?.value || 'portrait'
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
    fillMangaFormFromParams(data.params || {}, autoRun);
}

async function loadMangaHistory() {
    const box = document.getElementById('manga_history_list');
    if (!box) return;
    if (!getToken()) {
        box.innerHTML = '登录后查看最近生成的漫剧草稿。';
        return;
    }
    const res = await authFetch('/api/manga/history');
    const data = await res.json();
    mangaHistoryCache = Array.isArray(data.items) ? data.items : [];
    box.innerHTML = mangaHistoryCache.length ? mangaHistoryCache.map((item) => `<div class="key-item"><div class="key-row"><strong>${escapeHtml(item.project_name || item.project_id || '历史记录')}</strong><span class="key-badge">${escapeHtml(item.mode === 'draft_builder' ? `草稿 ${item.scene_count || 0} 场` : '素材')}</span></div><div class="muted">${escapeHtml(item.draft_name || item.created_at || '-')}</div><div class="key-actions"><button class="effect-add" type="button" onclick="fillMangaHistory(${item.id})">带入脚本</button><button class="effect-add" type="button" onclick="regenerateFromHistory(${item.id})">重新生成</button></div></div>`).join('') : '暂无历史';
}

function fillMangaHistory(id) {
    const item = mangaHistoryCache.find((entry) => Number(entry.id) === Number(id));
    if (!item) return;
    fillMangaFormFromParams(item.params || {}, false);
    setMangaStatus('已带入历史脚本，可继续修改后重新生成。');
}

async function regenerateFromHistory(id) {
    const res = await authFetch(`/api/manga/history/${id}/regenerate`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        setMangaStatus(data.error || '重新生成失败');
        return;
    }
    renderMangaDraftResult(data);
    setMangaStatus(data.message || '已重新生成');
    await loadMangaHistory();
}

async function redownloadFromHistory(id) {
    const res = await authFetch(`/api/manga/history/${id}/redownload`, { method: 'POST' });
    const data = await res.json();
    if (!res.ok || data.ok === false) {
        setMangaStatus(data.error || '重新下载失败');
        return;
    }
    renderMangaDraftResult(data);
    setMangaStatus(data.message || '已重新生成');
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

function initAiWorkspace() {
    refreshAiMaterials();
    document.getElementById('ai_provider_select')?.addEventListener('change', updateAiProviderGuideHint);
    if (runtimeFeatures.manga) {
        loadMangaTemplates();
        loadMangaHistory();
        renderMangaDraftResult({});
    }
}
