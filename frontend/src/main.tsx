import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Activity, Archive, ArrowUpRight, Check, CheckCircle2, ChevronDown, ChevronRight, CircleHelp, CirclePlus, ExternalLink, FileClock, Folder, Globe2, Layers3, Link2, LoaderCircle, LogOut, MoreHorizontal, Pin, Plus, Radio, RefreshCw, RotateCcw, Search, Settings2, ShieldCheck, SlidersHorizontal, Trash2, Upload, Workflow, X, Zap } from 'lucide-react';
import { api, post, ApiError, type Campaign, type Config, type Offer, type Operation, type Ref, type References, type Stream } from './api';
import './styles.css';

const date = (value: string) => new Date(value).toLocaleString('ru-RU', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const statusLabels: Record<string, string> = { succeeded: 'Выполнено', running: 'В процессе', unknown: 'Нужна сверка', failed: 'Не выполнено', conflict: 'Конфликт' };
const initials = (name: string) => name.replace(/[^\p{L}\p{N}\s]/gu, '').split(/\s+/).slice(0, 2).map(x => x[0]).join('').toUpperCase();

function Brand() { return <span className="brand"><span className="brand-mark"><Workflow size={21} strokeWidth={2.4}/></span>adrobot<span className="brand-period">.</span></span>; }
function Spinner() { return <LoaderCircle size={17} className="spin"/>; }
function Modal({ title, subtitle, children, close }: { title: string; subtitle?: string; children: React.ReactNode; close: () => void }) {
  const element = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const el = element.current!;
    const focusable = () => Array.from(el.querySelectorAll<HTMLElement>('button:not(:disabled), input, select, a[href]'));
    focusable()[0]?.focus();
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close();
      if (e.key === 'Tab') { const items = focusable(); if (e.shiftKey && document.activeElement === items[0]) { e.preventDefault(); items.at(-1)?.focus(); } else if (!e.shiftKey && document.activeElement === items.at(-1)) { e.preventDefault(); items[0]?.focus(); } }
    };
    document.addEventListener('keydown', handler);
    return () => { document.removeEventListener('keydown', handler); previous?.focus(); };
  }, [close]);
  return <div className="modal-overlay" onMouseDown={e => { if (e.target === e.currentTarget) close(); }}><div className="modal" ref={element} role="dialog" aria-modal="true" aria-label={title}><div className="modal-head"><div><h2>{title}</h2>{subtitle && <p>{subtitle}</p>}</div><button className="icon-btn" onClick={close} aria-label="Закрыть"><X size={20}/></button></div>{children}</div></div>;
}

function OfferSearch({ select, excluded = [] }: { select: (x: Ref) => void; excluded?: number[] }) {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<Ref[]>([]);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setLoading(true); setError('');
    const timer = setTimeout(() => {
      api<{ items: Ref[] }>('/offers?query=' + encodeURIComponent(query), { signal: controller.signal }).then(x => setResults(x.items)).catch(e => { if (e.name !== 'AbortError') setError(e.message); }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    }, 300);
    return () => { clearTimeout(timer); controller.abort(); };
  }, [query, open]);
  return <div className="offer-search"><div className="input-icon"><Search size={17}/><input aria-label="Поиск оффера по ID или названию" placeholder="Поиск по названию или ID оффера…" value={query} onFocus={() => setOpen(true)} onChange={e => { setQuery(e.target.value); setOpen(true); }}/>{open && <button type="button" className="icon-btn" aria-label="Закрыть поиск" onClick={() => setOpen(false)}><X size={15}/></button>}</div>{open && <div className="search-popover">{loading ? <p className="muted"><Spinner/> Ищем офферы…</p> : error ? <p className="error-text">{error}</p> : !results.length ? <p className="muted">Офферы не найдены</p> : results.map(x => <button type="button" key={x.id} disabled={excluded.includes(x.id)} onClick={() => { select(x); setOpen(false); setQuery(''); }}><span className="offer-avatar small">{initials(x.name)}</span><span><strong>{x.name}</strong><small>#{x.id}</small></span>{excluded.includes(x.id) ? <Check size={17}/> : <Plus size={17}/>}</button>)}</div>}</div>;
}

function CreateForm({ close, busy, run }: { close: () => void; busy: boolean; run: (data: unknown) => Promise<void> }) {
  const [refs, setRefs] = useState<References | null>(null);
  const [countries, setCountries] = useState<{ code: string; name: string }[]>([]);
  const [error, setError] = useState('');
  const [offer, setOffer] = useState<Ref | null>(null);
  const [form, setForm] = useState({ name: '', geo_code: 'AU', domain_id: '', group_id: '', traffic_source_id: '' });
  useEffect(() => { Promise.all([api<References>('/reference'), api<{ code: string; name: string }[]>('/reference/countries')]).then(([r, c]) => { setRefs(r); setCountries(c); setForm(f => ({ ...f, domain_id: String(r.domains[0]?.id || ''), group_id: String(r.groups[0]?.id || ''), traffic_source_id: String(r.traffic_sources[0]?.id || '') })); }).catch(e => setError(e.message)); }, []);
  const change = (key: keyof typeof form, value: string) => setForm(x => ({ ...x, [key]: value }));
  const selectRef = (label: string, field: 'domain_id' | 'group_id' | 'traffic_source_id', rows: Ref[]) => <label>{label}<span className="select-wrap"><select required value={form[field]} onChange={e => change(field, e.target.value)}><option value="" disabled>Выберите…</option>{rows.map(x => <option key={x.id} value={x.id}>{x.name}</option>)}</select><ChevronDown size={15}/></span></label>;
  return <Modal title="Новая кампания" subtitle="Два потока. Всё готово к запуску." close={close}><form onSubmit={async e => { e.preventDefault(); setError(''); if (!offer) return setError('Выберите оффер из результатов поиска.'); try { await run({ ...form, offer_id: offer.id, domain_id: +form.domain_id, group_id: +form.group_id, traffic_source_id: +form.traffic_source_id }); } catch (e) { setError((e as Error).message); } }}>
    <fieldset disabled={busy}><label>Название кампании<input required maxLength={255} autoComplete="off" placeholder="Например, Beauty · Australia" value={form.name} onChange={e => change('name', e.target.value)}/></label>
    <label>Страна GEO<span className="select-wrap"><select value={form.geo_code} onChange={e => change('geo_code', e.target.value)}>{countries.map(x => <option key={x.code} value={x.code}>{x.code} · {x.name}</option>)}</select><ChevronDown size={15}/></span></label>
    <label>Оффер</label>{offer ? <div className="selected-offer"><span><strong>{offer.name}</strong><small>#{offer.id}</small></span><button type="button" className="icon-btn" onClick={() => setOffer(null)} aria-label="Сменить оффер"><X size={17}/></button></div> : <OfferSearch select={setOffer}/>}
    <div className="form-separator">Настройки Keitaro</div>{refs ? <>{selectRef('Домен', 'domain_id', refs.domains)}<div className="form-grid">{selectRef('Группа', 'group_id', refs.groups)}{selectRef('Источник', 'traffic_source_id', refs.traffic_sources)}</div></> : !error && <p className="muted"><Spinner/> Загружаем настройки…</p>}
    <div className="routing-preview"><Workflow size={19}/><p><strong>{form.geo_code} → Google</strong><span>Остальные страны → выбранный оффер · 100%</span></p></div>
    {error && <div className="inline-error" role="alert">{error}</div>}<div className="modal-actions"><button type="button" className="btn secondary" onClick={close}>Отмена</button><button className="btn primary" disabled={!refs || !offer || busy}>{busy ? <Spinner/> : <Plus size={17}/>}Создать кампанию</button></div></fieldset></form></Modal>;
}

function OfferRow({ offer, locked, action }: { offer: Offer; locked: boolean; action: (action: string, offer: Offer, share?: number) => void }) {
  const [share, setShare] = useState(String(offer.share));
  useEffect(() => setShare(String(offer.share)), [offer.share]);
  return <tr className={!offer.active ? 'removed' : ''}><td><div className="offer-identity"><span className={'offer-avatar tone-' + (offer.offer_id % 4)}>{initials(offer.name)}</span><span><strong>{offer.name}</strong><small>#{offer.offer_id}{offer.new ? ' · Новый' : !offer.active ? offer.published_active ? ' · Будет удалён' : ' · В архиве' : offer.remote_state === 'disabled' ? ' · Отключён в Keitaro' : ''}</small></span></div></td><td><div className="share-control"><input aria-label={'Доля ' + offer.offer_id} type="number" min="0" max="100" step="1" disabled={locked || !offer.active} value={share} onChange={e => setShare(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && share !== '' && Number.isInteger(+share)) action('pin-value', offer, +share); }}/><span>%</span><button title={offer.pinned ? 'Снять закрепление' : 'Закрепить долю'} aria-label={(offer.pinned ? 'Снять закрепление ' : 'Закрепить долю ') + offer.offer_id} className={'pin-button ' + (offer.pinned ? 'pinned' : '')} disabled={locked || !offer.active || share === '' || !Number.isInteger(+share) || +share < 0 || +share > 100} onClick={() => action(share !== String(offer.share) ? 'pin-value' : 'pin', offer, +share)}><Pin size={15} fill={offer.pinned ? 'currentColor' : 'none'}/></button>{share !== String(offer.share) && <button className="apply-share" disabled={locked || share === '' || !Number.isInteger(+share) || +share < 0 || +share > 100} onClick={() => action('pin-value', offer, +share)} title="Применить и закрепить"><Check size={15}/></button>}</div></td><td><span className={'offer-state ' + (!offer.active ? 'archived' : offer.pinned ? 'fixed' : '')}>{!offer.active ? 'Удалён' : offer.pinned ? <><Pin size={11}/> Закреплён</> : 'Авто'}</span></td><td className="row-actions">{offer.active ? <button className="btn text danger-hover" aria-label={"Удалить оффер " + offer.offer_id} disabled={locked} onClick={() => action('remove', offer)}><Trash2 size={15}/><span>Удалить</span></button> : <button className="btn text" aria-label={"Вернуть оффер " + offer.offer_id} disabled={locked} onClick={() => action('restore', offer)}><RotateCcw size={15}/><span>Вернуть</span></button>}</td></tr>;
}

function StreamCard({ stream, busy, mutate, push, reconcile }: { stream: Stream; busy: boolean; mutate: (s: Stream, path: string, body?: object, method?: string) => Promise<void>; push: (s: Stream) => void; reconcile: (id: string) => void }) {
  const [showArchive, setShowArchive] = useState(true);
  const [addOpen, setAddOpen] = useState(false);
  const [expanded, setExpanded] = useState(true);
  const active = stream.offers.filter(x => x.active);
  const archived = stream.offers.filter(x => !x.active);
  const locked = busy || !!stream.busy_operation || stream.missing;
  const action = (act: string, offer: Offer, share?: number) => {
    if (act === 'pin' || act === 'pin-value') void mutate(stream, `/offers/${offer.id}`, { pinned: act === 'pin-value' || !offer.pinned, share }, 'PATCH');
    else void mutate(stream, `/offers/${offer.id}/${act}`);
  };
  return <section className={'stream-card ' + (stream.dirty ? 'is-dirty ' : '') + (stream.missing ? 'is-missing' : '')}>
    <div className="stream-header"><div className="stream-title"><button className="icon-btn" aria-label={expanded ? 'Свернуть поток' : 'Развернуть поток'} onClick={() => setExpanded(!expanded)}><ChevronDown size={18} className={!expanded ? 'collapsed' : ''}/></button><span className="stream-icon"><Layers3 size={19}/></span><div><h3>{stream.name}<span className={'badge ' + (stream.missing ? 'red' : stream.dirty ? 'amber' : 'green')}>{stream.missing ? 'Удалён в Keitaro' : stream.busy_operation ? 'Нужна сверка' : stream.dirty ? 'Не опубликован' : 'Синхронизирован'}</span></h3><p>Поток #{stream.remote_id}<span>·</span>Позиция {stream.position}{stream.editable && <><span>·</span>{active.length} офферов</>}</p></div></div><span className="stream-total">{stream.editable ? <><strong>{active.reduce((sum, x) => sum + x.share, 0)}%</strong> трафика</> : <span className="muted">Без офферов</span>}</span></div>
    {expanded && <>{stream.busy_operation && <div className="draft-banner"><FileClock size={17}/><span>Результат публикации требует сверки с Keitaro.</span><button className="btn secondary compact" disabled={busy} onClick={() => reconcile(stream.busy_operation!)}>Сверить</button></div>}
    {stream.editable ? <><div className="stream-tools"><span className="eyebrow">ОФФЕРЫ ПОТОКА</span><div>{archived.length > 0 && <button className={'btn text compact ' + (showArchive ? 'selected' : '')} onClick={() => setShowArchive(!showArchive)}><Archive size={14}/>{showArchive ? 'Скрыть архив' : `Архив (${archived.length})`}</button>}<button className="btn secondary compact" disabled={locked} onClick={() => setAddOpen(!addOpen)}><Plus size={15}/>Добавить оффер</button></div></div>
    {addOpen && <div className="inline-search"><OfferSearch excluded={active.map(x => x.offer_id)} select={x => { void mutate(stream, '/offers', { offer_id: x.id }); setAddOpen(false); }}/></div>}
    <div className="table-scroll"><table className="offers-table"><thead><tr><th>Оффер</th><th>Доля трафика</th><th>Распределение</th><th/></tr></thead><tbody>{stream.offers.filter(x => x.active || showArchive).map(x => <OfferRow key={x.id} offer={x} locked={locked} action={action}/>)}</tbody></table></div>
    {stream.dirty ? <div className="draft-footer"><span><span className="status-dot amber-dot"/> Изменения сохранены в черновике</span><div><button className="btn secondary compact" disabled={locked} onClick={() => void mutate(stream, '/cancel')}><RotateCcw size={14}/>Отменить</button><button className="btn primary compact" disabled={locked} onClick={() => push(stream)}><Upload size={14}/>Push to Keitaro</button></div></div> : <div className="stream-footer"><ShieldCheck size={14}/><span>Изменения появятся в Keitaro только после публикации</span><span className="revision">rev. {stream.revision}</span></div>}</> : <div className="readonly-stream"><Globe2 size={23}/><div><strong>Поток без офферов</strong><p>Его настройки управляются в Keitaro. Редактор сохраняет этот поток без изменений.</p></div></div>}</>}
  </section>;
}

function App() {
  const [auth, setAuth] = useState<{ authenticated: boolean; requires_login: boolean; mode: string } | null>(null);
  const [password, setPassword] = useState('');
  const [config, setConfig] = useState<Config | null>(null);
  const [campaigns, setCampaigns] = useState<Campaign[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [page, setPage] = useState('campaigns');
  const [query, setQuery] = useState('');
  const [dirtyOnly, setDirtyOnly] = useState(false);
  const [modal, setModal] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [toast, setToast] = useState<{ message: string; error: boolean } | null>(null);
  const [operations, setOperations] = useState<Operation[]>([]);
  const [importId, setImportId] = useState('');
  const [remote, setRemote] = useState<{ id: number; name: string; offers: { offer_id: number; share: number }[] }[]>([]);
  const idempotency = useRef(new Map<string, string>());
  const selected = campaigns.find(x => x.id === selectedId) || null;
  const closeModal = useCallback(() => setModal(null), []);
  const notify = (message: string, error = false) => setToast({ message, error });
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(null), 6500); return () => clearTimeout(t); } }, [toast]);
  const load = useCallback(async () => {
    const [cfg, rows, ops] = await Promise.all([api<Config>('/config'), api<Campaign[]>('/campaigns'), api<Operation[]>('/operations')]);
    setConfig(cfg); setCampaigns(rows); setOperations(ops);
  }, []);
  useEffect(() => { api<typeof auth>('/auth/me').then(setAuth).catch(e => { setError(e.message); setLoading(false); }); }, []);
  useEffect(() => { if (auth?.authenticated) { setLoading(true); load().catch(e => setError(e.message)).finally(() => setLoading(false)); } else if (auth) setLoading(false); }, [auth, load]);
  const perform = async (fn: () => Promise<void>) => { if (busy) return; setBusy(true); try { await fn(); } catch (e) { if (e instanceof ApiError && e.status === 401) setAuth(x => x && ({ ...x, authenticated: false })); notify((e as Error).message, true); } finally { setBusy(false); } };
  const opRequest = async (path: string, body: unknown) => {
    const identity = path + JSON.stringify(body);
    const key = idempotency.current.get(identity) || crypto.randomUUID();
    idempotency.current.set(identity, key);
    const result = await post<Operation>(path, body, key);
    idempotency.current.delete(identity);
    return result;
  };
  const handleOp = (op: Operation) => { if (op.status === 'succeeded') notify('Изменения подтверждены в Keitaro'); else notify(op.error || 'Операция ожидает сверки. Откройте журнал операций.', true); };
  const mutate = async (stream: Stream, path: string, body = {}, method = 'POST') => perform(async () => {
    await api(`/streams/${stream.id}${path}`, { method, body: JSON.stringify({ ...body, expected_revision: stream.revision }) });
    await load();
  });
  const reconcile = (id: string) => void perform(async () => { handleOp(await post<Operation>(`/operations/${id}/reconcile`)); await load(); });
  const openRemote = async () => { if (!selected) return; if (config?.mode === 'demo') { setRemote(await api(`/demo/remote/${selected.remote_id}`)); setModal('remote'); } else window.open(config!.keitaro_url.replace(/\/$/, '').replace(/\/admin_api\/v1$/, '') + '/admin/#!/campaigns/' + selected.remote_id, '_blank', 'noopener,noreferrer'); };
  const pending = operations.filter(x => ['unknown', 'running'].includes(x.status));
  const totalStreams = campaigns.reduce((n, x) => n + x.streams.length, 0);
  const dirtyCount = campaigns.reduce((n, x) => n + x.streams.filter(s => s.dirty).length, 0);
  const visible = campaigns.filter(x => `${x.name} ${x.remote_id}`.toLowerCase().includes(query.toLowerCase()) && (!dirtyOnly || x.streams.some(s => s.dirty)));

  if (!auth || loading) return <div className="boot"><Brand/><Spinner/><p>Подключаем рабочее пространство…</p>{error && <div className="inline-error">{error}<button className="btn secondary" onClick={() => location.reload()}>Повторить</button></div>}</div>;
  if (!auth.authenticated) return <div className="login-page"><Brand/><form onSubmit={e => { e.preventDefault(); void perform(async () => { await post('/auth/login', { password }); setAuth(await api('/auth/me')); }); }}><span className="login-icon"><ShieldCheck size={28}/></span><h1>С возвращением</h1><p>Войдите в рабочее пространство кампаний.</p><label>Пароль оператора<input autoFocus type="password" required value={password} onChange={e => setPassword(e.target.value)} autoComplete="current-password"/></label><button className="btn primary" disabled={busy}>{busy ? <Spinner/> : null}Войти</button></form>{toast && <div className="toast error-toast" role="alert">{toast.message}</div>}</div>;

  return <div className="app-shell"><aside className="sidebar"><Brand/><div className="workspace-switch"><span className="workspace-avatar">A</span><span><strong>Adrobot workspace</strong><small>Campaign management</small></span><ChevronDown size={15}/></div><div className="nav-label">РАБОЧЕЕ ПРОСТРАНСТВО</div><nav><button className={page === 'campaigns' ? 'active' : ''} onClick={() => { setPage('campaigns'); setSelectedId(null); }}><Layers3 size={19}/>Кампании<span className="nav-count">{campaigns.length}</span></button><button className={page === 'offers' ? 'active' : ''} onClick={() => { setPage('offers'); setSelectedId(null); }}><Link2 size={19}/>Каталог офферов</button><button className={page === 'operations' ? 'active' : ''} onClick={() => { setPage('operations'); setSelectedId(null); }}><FileClock size={19}/>Операции{pending.length > 0 && <span className="nav-count warning-count">{pending.length}</span>}</button></nav><div className="sidebar-bottom"><div className="connection-card"><span className="connection-icon"><Radio size={18}/></span><strong>Keitaro API</strong><span className={'connection-tag ' + (config?.mode === 'demo' ? '' : 'live-tag')}>{config?.mode === 'demo' ? 'DEMO' : 'LIVE'}</span><p>{config?.mode === 'demo' ? 'Изолированная демосреда' : 'Рабочее подключение'}</p><button onClick={() => setModal('integration')}>Настройки подключения<ChevronRight size={14}/></button></div><button className="sidebar-help" onClick={() => setModal('help')}><CircleHelp size={18}/>Как работает редактор</button><div className="profile"><span className="profile-avatar">OP</span><span><strong>Оператор</strong><small>Рабочее пространство</small></span>{auth.requires_login && <button className="icon-btn" aria-label="Выйти" onClick={() => void perform(async () => { await post('/auth/logout'); setAuth(await api('/auth/me')); })}><LogOut size={17}/></button>}</div></div></aside>
    <div className="main-shell"><header className="topbar"><div className="breadcrumbs"><Folder size={15}/><span>Workspace</span><ChevronRight size={14}/><button onClick={() => { setPage('campaigns'); setSelectedId(null); }}>Кампании</button>{selected && <><ChevronRight size={14}/><span>{selected.name}</span></>}</div><div className="topbar-right"><span className="environment"><span className="status-dot"/>{config?.mode === 'demo' ? 'Деморежим' : 'Keitaro Live'}</span><span className="topbar-divider"/><button className="icon-btn" title="Настройки" aria-label="Настройки подключения" onClick={() => setModal('integration')}><Settings2 size={18}/></button></div></header>
    <main>{error ? <div className="inline-error">{error}<button className="btn secondary" onClick={() => void perform(async () => { await load(); setError(''); })}>Повторить</button></div> : null}
      {page === 'campaigns' && !selected && <><div className="page-heading"><div><div className="eyebrow green-text">CAMPAIGN WORKSPACE</div><h1>Кампании</h1><p>Управляйте потоками и распределяйте трафик в одном месте.</p></div><button className="btn primary" onClick={() => setModal('create')}><Plus size={18}/>Новая кампания</button></div>
      <div className="summary-grid"><div className="summary-card"><span className="summary-icon mint"><Layers3 size={21}/></span><span>Всего кампаний<strong>{campaigns.length.toString().padStart(2, '0')}</strong></span><span className="summary-label">В рабочем пространстве</span></div><div className="summary-card"><span className="summary-icon blue"><Workflow size={21}/></span><span>Потоки<strong>{totalStreams.toString().padStart(2, '0')}</strong></span><span className="summary-label">Загружено из Keitaro</span></div><div className="summary-card"><span className="summary-icon sand"><FileClock size={21}/></span><span>Черновики<strong>{dirtyCount.toString().padStart(2, '0')}</strong></span><span className="summary-label">Ожидают публикации</span></div></div>
      <section className="campaign-list"><div className="list-toolbar"><div className="tabs"><button className={!dirtyOnly ? 'active' : ''} onClick={() => setDirtyOnly(false)}>Все кампании<span>{campaigns.length}</span></button><button className={dirtyOnly ? 'active' : ''} onClick={() => setDirtyOnly(true)}>С черновиками<span>{campaigns.filter(x => x.streams.some(s => s.dirty)).length}</span></button></div><div className="list-controls"><div className="input-icon search-campaign"><Search size={16}/><input aria-label="Поиск кампаний" placeholder="Найти кампанию…" value={query} onChange={e => setQuery(e.target.value)}/></div><button className="btn secondary compact" onClick={() => setModal('import')}><Upload size={15}/>Импорт по ID</button></div></div>
      <div className="table-scroll"><table className="campaign-table"><thead><tr><th>Название кампании</th><th>Статус</th><th>Потоки</th><th>Синхронизация</th><th/></tr></thead><tbody>{visible.map(c => { const dirty = c.streams.some(s => s.dirty); const uncertain = c.streams.some(s => s.busy_operation); return <tr key={c.id} onClick={() => setSelectedId(c.id)}><td><div className="campaign-identity"><span className="campaign-avatar"><Workflow size={21}/></span><span><button onClick={() => setSelectedId(c.id)}>{c.name}</button><small>#{c.remote_id} <span>·</span> {c.config.alias || 'Keitaro campaign'}</small></span></div></td><td><span className={'badge ' + (dirty || uncertain ? 'amber' : 'green')}><span className="status-dot"/>{uncertain ? 'Нужна сверка' : dirty ? 'Есть черновик' : 'Синхронизирована'}</span></td><td><span className="stream-count"><Layers3 size={15}/>{c.streams.length}</span></td><td className="date-cell">{date(c.synced_at)}</td><td><button className="icon-btn" aria-label={'Открыть ' + c.name}><ChevronRight size={18}/></button></td></tr>; })}</tbody></table></div>
      {!visible.length && <div className="empty-state"><Layers3 size={32}/><h3>{query || dirtyOnly ? 'Кампании не найдены' : 'Первая кампания начинается здесь'}</h3><p>{query || dirtyOnly ? 'Измените поиск или выбранный фильтр.' : 'Создайте кампанию или импортируйте её из Keitaro по ID.'}</p>{!query && !dirtyOnly && <button className="btn primary" onClick={() => setModal('create')}>Создать кампанию</button>}</div>}<div className="list-footer"><span>{visible.length} из {campaigns.length} кампаний</span><span>Данные вашего рабочего пространства</span></div></section>
      <div className="workspace-note"><ShieldCheck size={18}/><div><strong>Вы управляете. Keitaro распределяет.</strong><p>Редактируйте локально, публикуйте, когда всё готово. Ваши черновики сохраняются автоматически.</p></div></div></>}

      {page === 'campaigns' && selected && <><button className="back-link" onClick={() => setSelectedId(null)}>Все кампании</button><div className="page-heading editor-heading"><div><div className="eyebrow green-text">CAMPAIGN EDITOR</div><h1>{selected.name}</h1><p>Кампания #{selected.remote_id}<span className="inline-divider">·</span>Обновлено {date(selected.synced_at)}</p></div><div className="heading-actions"><button className="btn secondary" disabled={busy} onClick={() => void perform(openRemote)}><ExternalLink size={16}/>{config?.mode === 'demo' ? 'Демотрекер' : 'View in Keitaro'}</button><button className="btn primary" disabled={busy || selected.streams.some(s => s.dirty || s.busy_operation)} title="Сначала опубликуйте или отмените черновики" onClick={() => void perform(async () => { await post(`/campaigns/${selected.id}/fetch`); await load(); notify('Потоки загружены из Keitaro'); })}>{busy ? <Spinner/> : <RefreshCw size={16}/>}Fetch streams</button></div></div><div className="editor-meta"><span><Globe2 size={15}/>{config?.mode === 'demo' ? 'track.example.test' : 'Домен #' + selected.config.domain_id}</span><span><Folder size={15}/>Группа #{selected.config.group_id}</span><span><Radio size={15}/>Источник #{selected.config.traffic_source_id}</span><span className="meta-right"><ShieldCheck size={15}/>Черновики сохраняются автоматически</span></div>
      {selected.streams.some(x => x.dirty) && <div className="editor-notice"><FileClock size={17}/><span>Есть неопубликованные изменения. Для загрузки из Keitaro опубликуйте или отмените каждый черновик.</span></div>}
      <div className="streams-heading"><h2>Потоки кампании <span>{selected.streams.length}</span></h2><span>Обрабатываются по порядку</span></div>{selected.streams.map(s => <StreamCard key={s.id} stream={s} busy={busy} mutate={mutate} push={s => void perform(async () => { handleOp(await opRequest(`/streams/${s.id}/push`, { expected_revision: s.revision })); await load(); })} reconcile={reconcile}/>)}{!selected.streams.length && <div className="empty-state"><Workflow size={30}/><h3>В этой кампании нет потоков</h3><p>Создайте их в Keitaro и выполните Fetch streams.</p></div>}</>}

      {page === 'offers' && <><div className="page-heading"><div><div className="eyebrow green-text">OFFER LIBRARY</div><h1>Каталог офферов</h1><p>Найдите оффер по названию или его ID в Keitaro.</p></div></div><div className="catalog-card"><OfferSearch select={x => notify(`${x.name} · ID ${x.id}. Добавьте его в нужном потоке кампании.`)}/><div className="workspace-note"><Link2 size={22}/><div><strong>Один каталог — несколько потоков</strong><p>Офферы создаются в Keitaro. Здесь вы выбираете существующий оффер для кампании.</p></div></div></div></>}

      {page === 'operations' && <><div className="page-heading"><div><div className="eyebrow green-text">ACTIVITY LOG</div><h1>Операции</h1><p>Создание кампаний, публикация и сверка с Keitaro.</p></div><button className="btn secondary" disabled={busy} onClick={() => void perform(load)}><RefreshCw size={16}/>Обновить</button></div><section className="operations-list">{operations.map(op => <div className="operation-row" key={op.id}><span className={'operation-icon ' + (op.status === 'succeeded' ? 'success' : '')}>{op.kind === 'create' ? <CirclePlus size={21}/> : <Upload size={21}/>}</span><div className="operation-detail"><strong>{op.kind === 'create' ? 'Создание кампании' : 'Публикация потока'}</strong><small>{date(op.created_at)} · {op.id.slice(0, 8)} · {op.step}</small>{op.error && <p>{op.error}</p>}</div><span className={'badge ' + (op.status === 'succeeded' ? 'green' : 'amber')}>{statusLabels[op.status] || op.status}</span>{['unknown', 'running'].includes(op.status) && <button className="btn secondary compact" disabled={busy} onClick={() => reconcile(op.id)}>Сверить</button>}</div>)}{!operations.length && <div className="empty-state"><Activity size={30}/><h3>Операций пока нет</h3><p>Здесь появятся результаты создания и публикации кампаний.</p></div>}</section></>}
      <footer className="page-footer"><span>adrobot <span> / </span> Campaign workspace</span><span><ShieldCheck size={13}/>FastAPI · SQLAlchemy · React</span></footer>
    </main></div>

    {modal === 'create' && <CreateForm close={closeModal} busy={busy} run={async data => { setBusy(true); try { const op = await opRequest('/campaigns', data); await load(); handleOp(op); closeModal(); if (op.data.campaign_id) { setSelectedId(op.data.campaign_id); setPage('campaigns'); } else setPage('operations'); } finally { setBusy(false); } }}/> }
    {modal === 'import' && <Modal title="Импорт кампании" subtitle="Укажите ID существующей кампании Keitaro." close={closeModal}><form onSubmit={e => { e.preventDefault(); void perform(async () => { const c = await post<Campaign>('/campaigns/import', { remote_id: +importId }); await load(); setSelectedId(c.id); setPage('campaigns'); closeModal(); notify('Кампания импортирована'); }); }}><label>ID кампании<input type="number" min="1" required value={importId} onChange={e => setImportId(e.target.value)} placeholder={config?.mode === 'demo' ? '93212' : 'Например, 93212'}/></label><div className="modal-actions"><button className="btn primary" disabled={busy}>{busy ? <Spinner/> : <Upload size={16}/>}Загрузить кампанию</button></div></form></Modal>}
    {modal === 'integration' && <Modal title="Подключение Keitaro" subtitle="Ключ API хранится только на сервере." close={closeModal}><div className="integration-status"><Radio size={23}/><div><strong>{config?.mode === 'demo' ? 'Демонстрационный режим' : 'Рабочий режим'}</strong><p>{config?.mode === 'demo' ? 'Все изменения сохраняются в отдельном демотрекере.' : config?.keitaro_url}</p></div><span className="badge green">{config?.mode?.toUpperCase()}</span></div><p className="help-copy">{config?.mode === 'demo' ? 'Можно создавать кампании, менять состав офферов и публиковать изменения без доступа к реальному Keitaro. Кнопка «Демотрекер» показывает состояние до и после публикации.' : 'Изменения публикуются в подключённый Keitaro. Не редактируйте один поток одновременно здесь и в админке трекера.'}</p><div className="routing-preview"><ShieldCheck size={20}/><p><strong>Настройка через серверную конфигурацию</strong><span>Инструкция подключения и переменные окружения находятся в README проекта.</span></p></div></Modal>}
    {modal === 'help' && <Modal title="От черновика до публикации" subtitle="Управляйте составом офферов без потери истории." close={closeModal}><div className="help-steps"><div><span><RefreshCw size={20}/></span><p><strong>Загрузите потоки</strong>Fetch получает актуальную конфигурацию из Keitaro.</p></div><div><span><SlidersHorizontal size={20}/></span><p><strong>Настройте распределение</strong>Добавляйте и удаляйте офферы. Pin закрепляет долю, остаток распределяется поровну.</p></div><div><span><Upload size={20}/></span><p><strong>Опубликуйте, когда готовы</strong>Push записывает изменения в Keitaro. «Отменить» возвращает последний опубликованный состав.</p></div><div><span><Archive size={20}/></span><p><strong>История остаётся с вами</strong>Удалённые офферы попадают в архив. Их можно вернуть и снова опубликовать.</p></div></div></Modal>}
    {modal === 'remote' && <Modal title="Состояние демотрекера" subtitle="Это опубликованные данные. Локальные черновики здесь не видны." close={closeModal}><div className="remote-streams">{remote.map(s => <section key={s.id}><h3>{s.name} <small>#{s.id}</small></h3>{!s.offers.length ? <p className="muted">Поток-редирект · без офферов</p> : s.offers.map(o => <div className="remote-offer" key={o.offer_id}><span>Оффер #{o.offer_id}</span><strong>{o.share}%</strong><button className="icon-btn" title="Имитировать удаление напрямую в Keitaro" aria-label={'Удалить в демотрекере ' + o.offer_id} disabled={busy || s.offers.length <= 1} onClick={() => void perform(async () => { await post(`/demo/streams/${s.id}/remove/${o.offer_id}`); setRemote(await api(`/demo/remote/${selected!.remote_id}`)); notify('Удалено в демотрекере. Выполните Fetch для синхронизации обёртки.'); })}><Trash2 size={15}/></button></div>)}</section>)}</div><p className="help-copy">Удаление здесь имитирует правку напрямую в Keitaro. Вернитесь в редактор и нажмите Fetch, чтобы проверить синхронизацию архива.</p></Modal>}
    {toast && <div className={'toast ' + (toast.error ? 'error-toast' : '')} role={toast.error ? 'alert' : 'status'}>{toast.error ? <CircleHelp size={19}/> : <CheckCircle2 size={19}/>}<span>{toast.message}</span><button className="icon-btn" onClick={() => setToast(null)} aria-label="Закрыть уведомление"><X size={16}/></button></div>}
    {busy && <div className="busy-indicator" role="status"><Spinner/>Выполняем запрос…</div>}
  </div>;
}

createRoot(document.getElementById('root')!).render(<App/>);
