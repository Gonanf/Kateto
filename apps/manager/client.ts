import * as grpc from '@grpc/grpc-js';
import * as protoLoader from '@grpc/proto-loader';
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const packageDefinition = protoLoader.loadSync(join(__dirname, "../protos/manager/manager.proto"), {
  keepCase: true,
  longs: String,
  enums: String,
  defaults: true,
  oneofs: true
});

const protoDescriptor = grpc.loadPackageDefinition(packageDefinition);
const Manager = protoDescriptor.Manager;

const client = new Manager(
  '0.0.0.0:50051',
  grpc.credentials.createInsecure()
);

const prompt = process.argv[2] || "Hello, who are you?";

console.log(`\n> ${prompt}\n`);

const call = client.prompt({ text: prompt }, { deadline: Date.now() + 120000 });

const sleep = (ms: number) => new Promise(resolve => setTimeout(resolve, ms));

let buffer = '';

call.on('data', async (response: { token: string }) => {
  buffer += response.token;
  process.stdout.write(response.token);
  await sleep(75);
});

call.on('end', () => {
  console.log('\n\n[Stream ended]');
  process.exit(0);
});

call.on('error', (err: Error) => {
  console.error('\n[Stream error]:', err.message);
  process.exit(1);
});
