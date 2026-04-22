extends Panel
var server: UDPServer

# Called when the node enters the scene tree for the first time.
func _ready() -> void:
	server = UDPServer.new()
	server.listen(4242)


# Called every frame. 'delta' is the elapsed time since the previous frame.
func _process(delta: float) -> void:
	server.poll()
	if server.is_connection_available():
		var peer = server.take_connection()
		var packet = peer.get_packet()
		print("Received: '%s' %s:%s" % [packet.get_string_from_utf8(), peer.get_packet_ip(), peer.get_packet_port()])
		$RichTextLabel.text = packet.get_string_from_utf8()
		peer.put_packet("Hello from Godot!".to_utf8_buffer())
