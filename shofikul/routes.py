from flask import send_from_directory

def init_routes(app):

    @app.route("/shofikul/")
    @app.route("/shofikul/<path:filename>")
    def shofikul_page(filename="index.html"):
        return send_from_directory("shofikul", filename)