from app import create_app

app = create_app()

if __name__ == '__main__':
    port = 8900
    app.run(debug=True, port=port)