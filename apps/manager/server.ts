import * as grpc from '@grpc/grpc-js';
import * as protoLoader from '@grpc/proto-loader';
import { type PromptRequest, type PromptResponse } from "../protos/manager/typescript/manager_pb.ts";
import { createOpencode, createOpencodeClient, type Session } from "@opencode-ai/sdk/v2"
import { Effect, Layer, Context, Stream, Option } from "effect"
import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { error } from 'console';

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
const manager = protoDescriptor.Manager;
if (!manager) throw new Error("Expecting a Manager service in the proto, found nothing...")

enum Agents {
  Charlatan = "kateto-charlatan",
  Soñador = "kateto-soñador"
}


// TODO: Put this in an Effect and fork it
const opencode = await (async () => {
  try {
    console.log("Creating the server...")
    return await createOpencode({
      hostname: "127.0.0.1",
      port: 4096,
      config: {
        model: "opencode-go/qwen3.5-plus"
      }
    })
  } catch {
    console.log("A server already exists, connecting...")
    const client = createOpencodeClient({
      baseUrl: "http://127.0.0.1:4096"
    })
    return { client, server: null }
  }
})()

class SessionService extends Context.Tag("SessionService")<SessionService, Session>() { }

const useSession = Layer.effect(SessionService, Effect.gen(function* () {
  console.log("Creating session...")
  const session = yield* Effect.tryPromise({ try: () => opencode.client.session.create(), catch: (error) => new Error(`No se pudo crear la sesion: ${error}`) })
  if (session.error) return yield* Effect.fail(session.error)
  console.log("Created the session service with id", session.data.id)
  return session.data
}))


const program = (call: grpc.ServerWritableStream<any, PromptResponse>) => Effect.gen(function* () {
  console.log("Starting prompt handler...")
  const session = yield* SessionService

  // Subscribe to events BEFORE sending prompt so we don't miss any tokens
  console.log("Subscribing to events...")
  const events = yield* Effect.tryPromise({
    try: () => opencode.client.event.subscribe(),
    catch: (error) => new Error(`Cannot subscribe to events: ${error}`)
  })

  console.log("Event subscription keys:", Object.keys(events))
  console.log("Has stream:", "stream" in events)

  // Send prompt
  console.log("Sending prompt to", Agents.Charlatan)
  const response = yield* Effect.tryPromise({
    try: () => opencode.client.session.promptAsync({
      sessionID: session.id,
      parts: [{ type: "text", text: call.request.text }],
      agent: Agents.Charlatan.toString(),
    }),
    catch: (error) => new Error(`Cannot send prompt: ${error}`)
  })

  if (response.error) {
    console.error("Prompt failed:", response.error)
    return yield* Effect.fail(new Error(`Prompt failed: ${response.error}`))
  }

  console.log("Prompt response received:", JSON.stringify(response.data, null, 2))

  // If the response already has parts, stream them immediately
  // if (response.data?.parts && Array.isArray(response.data.parts)) {
  //   console.log("Streaming", response.data.parts.length, "parts from response")
  //   for (const part of response.data.parts) {
  //     console.log("Part:", part)
  //     if (part.type === "text") {
  //       call.write({ token: part.text } as PromptResponse)
  //     }
  //   }
  // }

  // Also process real-time events if stream is available
  if (events.stream) {
    console.log("Processing event stream for real-time updates...")

    const stream = Stream.fromAsyncIterable(
      events.stream,
      (e) => new Error(`Stream error: ${e}`)
    )

    var talking = false
    // Race stream processing against a 60s timeout
    yield* Effect.race(
      Stream.runForEach(stream, (event) => Effect.sync(() => {
        console.log("Event received:", event.type, JSON.stringify(event.properties))

        if (event.type == "message.part.updated" && event.properties.part.type == "text") {
          talking = true

          console.warn("Starting to talk...")
        }

        if (event.type === "message.part.delta" && talking) {
          const part = event.properties?.delta

          console.log("Writing token from event:", event)
          call.write({ token: part } as PromptResponse)

        }

        if (event.type === "session.idle") {
          talking = false
          call.end()
        }
      })),
      Effect.sleep("60 seconds").pipe(Effect.tap(() => console.log("Event stream timeout reached")))
    ).pipe(
      Effect.catchAll((error) => Effect.sync(() => console.error("Event stream failed:", error)))
    )
  }

  console.log("Closing gRPC call")
  call.end()
})


const server = new grpc.Server();

async function prompt(call: grpc.ServerWritableStream<any, PromptResponse>) {
  await Effect.runPromise(
    program(call).pipe(
      Effect.provide(useSession)
    )
  )
}

// Register the Manager service
server.addService(manager.service, {
  prompt: prompt
});

// Start the server
const PORT = 50051;
server.bindAsync(`0.0.0.0:${PORT}`, grpc.ServerCredentials.createInsecure(), (err, port) => {
  if (err) {
    console.error("Failed to start gRPC server:", err);
    process.exit(1);
  }
  console.log(`gRPC Manager server started on port ${port}`);
});


