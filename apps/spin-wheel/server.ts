import { serve } from 'bun';
import * as grpc from '@grpc/grpc-js';
import * as protoLoader from '@grpc/proto-loader';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { readFileSync, writeFileSync, existsSync } from 'fs';
import { $ } from "bun";
import { config } from 'process';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

type SpinItem = {
  id: string;
  label: string;
  checked: boolean;
};

type AffineBlock = {
  id: string;
  flavour?: string;
  text?: string;
  checked?: boolean;
};

type AffineRead = {
  blocks?: AffineBlock[];
  markdown: string;
};

const ITEMS_FILE = join(__dirname, 'items.json');
const ITEMS_METHOD: "FILE" | "AFFINE" = (process.env.ITEMS_METHOD as "FILE" | "AFFINE" | undefined) ?? "FILE";
const CONFIG_PATH = join(__dirname, 'config.json');
type ConfigState = {
  availability: string;
  teamPersons: string[];
};
let configState: ConfigState = {
  availability: 'Full Time',
  teamPersons: ['Chaos'],
};

function loadConfigFromDisk(): ConfigState {
  if (existsSync(CONFIG_PATH)) {
    try {
      const raw = readFileSync(CONFIG_PATH, 'utf-8');
      const parsed = JSON.parse(raw);
      const availability = typeof parsed?.availability === 'string' ? parsed.availability : '';
      const teamPersons = Array.isArray(parsed?.teamPersons) ? parsed.teamPersons.map(String) : [];
      return { availability, teamPersons };
    } catch {
      // fall back to env values
    }
  }
  return configState;
}

configState = loadConfigFromDisk();
const DIST_DIR = join(__dirname, 'dist');
const PORT = 3001;
const MANAGER_GRPC_ADDR = '0.0.0.0:50051';

async function loadItems(): Promise<SpinItem[]> {
  switch (ITEMS_METHOD) {
    case "FILE": {
      if (!existsSync(ITEMS_FILE)) return [];
      const data = JSON.parse(readFileSync(ITEMS_FILE, 'utf-8'));
      // Normalize to SpinItem[] regardless of how data was stored
      if (Array.isArray(data)) {
        return data.map((entry: unknown, idx: number) => {
          if (typeof entry === 'string') {
            return { id: String(idx), label: entry, checked: false };
          }
          // support legacy/object form {id,label,checked}
          if (typeof entry === 'object' && entry !== null) {
            const obj = entry as Record<string, unknown>;
            return {
              id: String(obj.id ?? idx),
              label: String(obj.label ?? obj.text ?? ''),
              checked: !!obj.checked
            };
          }
          return { id: String(idx), label: String(entry), checked: false };
        });
      }
      return [];
    }
    case "AFFINE": {
      const response = await $`bunx mcporter call affine.read_doc docId:${process.env.AFFINE_DOC_ID} includeMarkdown:true`.quiet();
      const content = await response.json() as { blocks?: AffineBlock[], markdown: string };
      const blocks: AffineBlock[] = (content.blocks ?? []).filter((b) => b.flavour === 'affine:list' && b.text) as AffineBlock[];
      const items: SpinItem[] = blocks.map((b) => ({
        id: String(b.id),
        label: String(b.text ?? ''),
        checked: !!(b.hasOwnProperty('checked') ? b.checked : false)
      }));
      return items;
    }
    default: {
      return []
    }
  }



}


async function saveItems(itemInput: string | SpinItem): Promise<void> {
  const item: SpinItem = typeof itemInput === 'string' ? { id: 'auto', label: itemInput, checked: false } : itemInput;
  if (ITEMS_METHOD === 'AFFINE') {
    const label = item.label;
    await $`bunx mcporter call affine.append_block docId:${process.env.AFFINE_DOC_ID} type:list style:todo text:"${label}" checked:false`.quiet();

    // Refresh local cache
    const refreshed = await loadItems();
    allItems = refreshed;
    return;
  }

  let arr: string[] = [];
  if (existsSync(ITEMS_FILE)) {
    try {
      const raw = readFileSync(ITEMS_FILE, 'utf-8');
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed)) arr = parsed.filter((e) => typeof e === 'string');
    } catch {
      arr = [];
    }
  }
  arr.push(item.label);
  writeFileSync(ITEMS_FILE, JSON.stringify(arr, null, 2));
  // Refresh cache
  allItems = await loadItems();
}


let usedItems = new Set<string>();
let allItems: SpinItem[] = await loadItems();

const packageDefinition = protoLoader.loadSync(
  join(__dirname, '../../packages/protos/manager/manager.proto'),
  {
    keepCase: true,
    longs: String,
    enums: String,
    defaults: true,
    oneofs: true
  }
);

const protoDescriptor = grpc.loadPackageDefinition(packageDefinition);
const Manager = (protoDescriptor as any).manager.Manager;

const grpcClient = new Manager(
  MANAGER_GRPC_ADDR,
  grpc.credentials.createInsecure()
);

function callManagerPrompt(text: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const call = grpcClient.prompt({ text, agent: "PRODUCT_OWNER" }, { deadline: Date.now() + 120000 });
    let buffer = '';

    call.on('data', (response: { token: string }) => {
      buffer += response.token;
    });

    call.on('end', () => resolve(buffer));
    call.on('error', (err: Error) => reject(err));
  });
}

function buildSprintPrompt(feature: string): string {
  let prompt = feature;
  try {
    const c = configState;
    if (c?.availability) {
      prompt += `\nAvailability: ${c.availability}`;
    }
    if (c?.teamPersons && c.teamPersons.length > 0) {
      prompt += `\nTeam: ${c.teamPersons.join(', ')}`;
    }
  } catch {
    // ignore config read issues, fall back to feature only
  }
  return prompt;
}

function serveStaticFile(path: string): Response | null {
  const filePath = join(DIST_DIR, path);
  if (!existsSync(filePath)) return null;
  const content = readFileSync(filePath);
  const ext = path.split('.').pop() || '';
  const mimeTypes: Record<string, string> = {
    html: 'text/html',
    js: 'application/javascript',
    css: 'text/css',
    json: 'application/json',
    png: 'image/png',
    svg: 'image/svg+xml',
    ico: 'image/x-icon'
  };
  return new Response(content, {
    headers: { 'Content-Type': mimeTypes[ext] || 'application/octet-stream' }
  });
}

// initialized above: let allItems: SpinItem[] = await loadItems()

const server = serve({
  port: PORT,
  async fetch(req) {
    const url = new URL(req.url);
    const pathname = url.pathname;

    if (pathname === '/api/items' && req.method === 'GET') {
      const items = allItems.map((it) => ({ label: it.label, checked: usedItems.has(it.label) || it.checked }));
      return Response.json({ items });
    }

    if (pathname === '/api/items' && req.method === 'POST') {
      const body = await req.json();
      // Support legacy {item: string} as well as new {label: string} or {item: {label}}
      let label: string | null = null;
      if (body?.item) {
        label = typeof body.item === 'string' ? body.item : String(body.item);
      } else if (body?.label) {
        label = typeof body.label === 'string' ? body.label : String(body.label);
      } else if (typeof body === 'string') {
        label = body;
      }
      if (label) {
        await saveItems(label);
        usedItems = new Set();
        return Response.json({ success: true });
      }
      return new Response(JSON.stringify({ success: false, error: 'No item label provided' }), { status: 400 });
    }

    // Alias for adding a single item directly via /api/items/add
    if (pathname === '/api/items/add' && req.method === 'POST') {
      const body = await req.json();
      const label = typeof body?.label === 'string' ? body.label : typeof body?.item === 'string' ? body.item : null;
      if (label) {
        await saveItems(label);
        return Response.json({ success: true });
      }
      return new Response(JSON.stringify({ success: false, error: 'No label provided' }), { status: 400 });
    }

    if (pathname === '/api/spin' && req.method === 'POST') {
      const body = await req.json();
      const winner: string = body.winner;

      /*
       * Explanation: The affine mcp that i am using does not have any kind of tool
       * to modify existing blocks, so what i have to do is get the markdown, modify it manually and put it again
       */
      if (ITEMS_METHOD == "AFFINE") {
        const response = await $`bunx mcporter call affine.read_doc docId:${process.env.AFFINE_DOC_ID} includeMarkdown:true`.quiet();
        const content = await response.json() as AffineRead;
        const currentMd = content.markdown;
        const newMarkdown = currentMd.replace(`- [ ] ${winner}`, `- [x] ${winner}`);
        await $`bunx mcporter call affine.replace_doc_with_markdown docId:${process.env.AFFINE_DOC_ID} markdown:${newMarkdown}`.quiet();
        allItems.forEach((i) => { if (i.label === winner) i.checked = true; });
      }
      usedItems.add(winner);

      const remaining = allItems.filter(l => !usedItems.has(l.label)).length;
      return Response.json({ winner, remaining });
    }

    // Delete a specific item by id
    if (pathname.startsWith('/api/items/') && req.method === 'DELETE') {
      const id = pathname.split('/').pop() || '';
      if (!id) return new Response('Not Found', { status: 404 });
      if (ITEMS_METHOD === 'AFFINE') {
        // Remove by block id from AFFINE doc
        const target = allItems.find((it) => it.id === id);
        if (!target) return new Response('Not Found', { status: 404 });
        // Read current markdown to modify
        const resp = await $`bunx mcporter call affine.read_doc docId:${process.env.AFFINE_DOC_ID} includeMarkdown:true`.quiet();
        const mdContent = await resp.json() as { markdown: string };
        const oldMd = mdContent.markdown ?? '';
        // Remove the line containing the item label
        const lines = oldMd.split('\n');
        const newMd = lines.filter((ln) => !ln.includes(target.label)).join('\n');
        await $`bunx mcporter call affine.replace_doc_with_markdown docId:${process.env.AFFINE_DOC_ID} markdown:${newMd}`.quiet();
        // Update local list
        allItems = allItems.filter((i) => i.id !== id);
      } else {
        // FILE mode: items.json is a string[]; delete by index id
        if (!existsSync(ITEMS_FILE)) return new Response('Not Found', { status: 404 });
        let arr: string[] = [];
        try {
          arr = JSON.parse(readFileSync(ITEMS_FILE, 'utf-8'));
        } catch {
          arr = [];
        }
        const idx = parseInt(id, 10);
        if (Number.isNaN(idx) || idx < 0 || idx >= arr.length) return new Response('Not Found', { status: 404 });
        arr.splice(idx, 1);
        writeFileSync(ITEMS_FILE, JSON.stringify(arr, null, 2));
        allItems = await loadItems();
      }
      return Response.json({ success: true, id });
    }

    if (pathname === '/api/generate-sprint-doc' && req.method === 'POST') {
      const body = await req.json();
      const feature: string = body.feature;

      try {
        const prompt = buildSprintPrompt(feature);
        const document = await callManagerPrompt(prompt);
        return Response.json({ document });
      } catch (err) {
        console.error('gRPC call failed:', err);
        return Response.json(
          { error: 'Failed to generate sprint document' },
          { status: 500 }
        );
      }
    }

    // Config endpoints
    if (pathname === '/api/config' && req.method === 'GET') {
      // Return current configuration derived from env/config.json
      const availability = configState.availability || '';
      const teamPersons = configState.teamPersons || [];
      return Response.json({ availability, teamPersons });
    }

    if (pathname === '/api/config' && req.method === 'POST') {
      const body = await req.json();
      const newAvail = typeof body?.availability === 'string' ? body.availability : undefined;
      const newTeam = Array.isArray(body?.teamPersons) ? body.teamPersons.map((s: unknown) => String(s).trim()).filter(Boolean) : undefined;
      // Update in-memory config
      if (newAvail !== undefined) configState.availability = newAvail;
      if (newTeam !== undefined) configState.teamPersons = newTeam;
      // Persist to disk
      const toPersist = {
        availability: configState.availability,
        teamPersons: configState.teamPersons,
      };
      try {
        writeFileSync(CONFIG_PATH, JSON.stringify(toPersist, null, 2));
      } catch {
        // ignore persistence errors
      }
      return Response.json({ success: true, config: toPersist });
    }

    if (pathname === '/api/reset-used' && req.method === 'POST') {
      usedItems.clear();
      return Response.json({ success: true });
    }

    // Reset all items and uncheck in AFFINE document as well
    if (pathname === '/api/reset' && req.method === 'POST') {
      usedItems.clear();
      if (ITEMS_METHOD === 'AFFINE') {
        const resp = await $`bunx mcporter call affine.read_doc docId:${process.env.AFFINE_DOC_ID} includeMarkdown:true`.quiet();
        const data = await resp.json() as { markdown: string };
        const newMd = (data.markdown ?? '').split('\n').map((ln) => ln.startsWith('- [x]') ? ln.replace('- [x]', '- [ ]') : ln).join('\n');
        await $`bunx mcporter call affine.replace_doc_with_markdown docId:${process.env.AFFINE_DOC_ID} markdown:${newMd}`.quiet();
        // refresh local items as unchecked
        allItems = await loadItems();
      }
      // also reset local in-memory items' checked flags
      allItems.forEach((it) => (it.checked = false));
      return Response.json({ success: true });
    }

    const staticFile = serveStaticFile(pathname === '/' ? 'index.html' : pathname);
    if (staticFile) return staticFile;

    return new Response('Not Found', { status: 404 });
  }
});

console.log(`Spin-wheel backend running on http://localhost:${PORT}`);
console.log(`Proxying LLM calls to manager gRPC at ${MANAGER_GRPC_ADDR}`);
