import * as grpc from '@grpc/grpc-js';
import * as protoLoader from '@grpc/proto-loader';
import { type PromptRequest, type PromptResponse } from "../protos/manager/typescript/manager_pb.ts";
import { createOpencode, createOpencodeClient, type Session } from "@opencode-ai/sdk"
import { Effect, Layer, Context, Stream, Option } from "effect"


const packageDefinition = protoLoader.loadSync("../protos/manager/manager.proto", {
  keepCase: true,
  longs: String,
  enums: String,
  defaults: true,
  oneofs: true
});

const protoDescriptor = grpc.loadPackageDefinition(packageDefinition);

const manager = protoDescriptor.manager;

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


const program = (call) => Effect.gen(function* () {
  console.log("Sending prompt...")
  const session = yield* SessionService

  console.log("Sending prompt to ", Agents.Charlatan.toString())
  const response = yield* Effect.tryPromise({
    try: () => opencode.client.session.prompt({
      path: { id: session.id },
      body: {
        parts: [{ type: "text", text: call.request.text }],
        agent: Agents.Charlatan.toString()
      }
    }),
    catch: (error) => new Error(`Cannot send prompt: ${error}`)
  })

  const events = yield* Effect.tryPromise({ try: () => opencode.client.event.subscribe(), catch: (error) => new Error("Cannot subscribe to events:", error) })

  const stream = Stream.fromAsyncIterable(events.stream, (e) => new Error("Error when getting the stream of events:", String(e)))

  Stream.runForEach(stream, (event) => Effect.sync(() => {
    if (event.type === "message.part.updated") {
      const part = event.properties.part;

      if (part.type === "text") {
        // Send text delta as token events
        call.write({
          prompt_response: {
            token: part.text
          },
        });
      }
    }

  }))

})


const server = new grpc.Server();

async function prompt(call) {

  await Effect.runPromise(
    program(call).pipe(
      Effect.provide(useSession)
    )
  )

}


