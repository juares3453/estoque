from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    session,
    jsonify,
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///estoque.db"
app.config["SECRET_KEY"] = "chave-secreta"  # Para utilizar mensagens flash
db = SQLAlchemy(app)


class Mercadoria(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False, unique=True)
    quantidade = db.Column(db.Integer, nullable=False)
    descricao = db.Column(db.String(200))
    preco = db.Column(db.Float)

    def __repr__(self):
        return f"<Mercadoria {self.nome}>"


class Usuario(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), nullable=False, unique=True)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Fornecedor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cnpj = db.Column(db.String(18), nullable=False, unique=True)
    nome = db.Column(db.String(100), nullable=False)
    endereco = db.Column(db.String(200), nullable=False)
    telefone = db.Column(db.String(15), nullable=False)
    email = db.Column(db.String(100), nullable=False)

    def __repr__(self):
        return f"<Fornecedor {self.nome}>"


class LogMovimentacao(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuario.id"), nullable=True)
    acao = db.Column(db.String(100), nullable=False)
    mercadoria_id = db.Column(db.Integer, db.ForeignKey("mercadoria.id"), nullable=True)
    descricao = db.Column(db.String(200), nullable=False)
    data_hora = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship("Usuario", backref=db.backref("logs", lazy=True))
    mercadoria = db.relationship("Mercadoria", backref=db.backref("logs", lazy=True))


# Inicializando o banco de dados
with app.app_context():
    db.create_all()


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Por favor, faça login para acessar esta página.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)

    return decorated_function


def registrar_log(acao, descricao, mercadoria_id=None):
    log = LogMovimentacao(
        usuario_id=session.get("user_id"),
        acao=acao,
        mercadoria_id=mercadoria_id,
        descricao=descricao,
    )
    db.session.add(log)
    db.session.commit()


@app.route("/")
@login_required
def index():
    mercadorias = Mercadoria.query.all()
    return render_template("index.html", mercadorias=mercadorias)


@app.route("/adicionar", methods=["GET", "POST"])
@login_required
def adicionar():
    if request.method == "POST":
        nome = request.form["nome"].strip().lower()
        quantidade = int(request.form["quantidade"])
        descricao = request.form["descricao"]
        preco = float(request.form["preco"])

        mercadoria_existente = Mercadoria.query.filter(
            db.func.lower(Mercadoria.nome) == nome
        ).first()
        if mercadoria_existente:
            flash("Já existe uma mercadoria com esse nome!", "error")
            return redirect(url_for("adicionar"))

        nova_mercadoria = Mercadoria(
            nome=nome, quantidade=quantidade, descricao=descricao, preco=preco
        )
        db.session.add(nova_mercadoria)
        db.session.commit()
        registrar_log(
            "Inserção",
            f"Mercadoria '{nova_mercadoria.nome}' adicionada com quantidade {quantidade}.",
            nova_mercadoria.id,
        )
        flash("Mercadoria adicionada com sucesso!", "success")
        return redirect(url_for("index"))

    return render_template("adicionar.html")


@app.route("/editar/<int:id>", methods=["GET", "POST"])
@login_required
def editar(id):
    mercadoria = Mercadoria.query.get_or_404(id)
    if request.method == "POST":
        mercadoria.nome = request.form["nome"].strip().lower()
        mercadoria.quantidade = int(request.form["quantidade"])
        mercadoria.descricao = request.form["descricao"]
        mercadoria.preco = float(request.form["preco"])
        db.session.commit()
        registrar_log(
            "Edição",
            f"Mercadoria '{mercadoria.nome}' editada. Quantidade: {mercadoria.quantidade}.",
            mercadoria.id,
        )
        flash("Mercadoria editada com sucesso!", "success")
        return redirect(url_for("index"))

    return render_template("editar.html", mercadoria=mercadoria)


@app.route("/excluir/<int:id>")
@login_required
def excluir(id):
    mercadoria = Mercadoria.query.get_or_404(id)
    db.session.delete(mercadoria)
    db.session.commit()
    registrar_log(
        "Exclusão", f"Mercadoria '{mercadoria.nome}' excluída.", mercadoria.id
    )
    flash("Mercadoria excluída com sucesso!", "success")
    return redirect(url_for("index"))


@app.route("/buscar_ajax", methods=["GET"])
@login_required
def buscar_ajax():
    query = request.args.get("query", "").strip().lower()
    resultados = Mercadoria.query.filter(Mercadoria.nome.like(f"%{query}%")).all()
    mercadorias = [
        {
            "id": mercadoria.id,
            "nome": mercadoria.nome,
            "quantidade": mercadoria.quantidade,
            "descricao": mercadoria.descricao,
            "preco": mercadoria.preco,
        }
        for mercadoria in resultados
    ]
    return jsonify(mercadorias)


@app.route("/movimentacoes")
@login_required
def movimentacoes():
    logs = LogMovimentacao.query.order_by(LogMovimentacao.data_hora.desc()).all()
    return render_template("movimentacoes.html", logs=logs)


@app.route("/fornecedores", methods=["GET", "POST"])
@login_required
def gerenciar_fornecedores():
    fornecedor_id = request.args.get("fornecedor_id")
    fornecedor = Fornecedor.query.get(fornecedor_id) if fornecedor_id else None

    if request.method == "POST":
        if fornecedor:  # Editando fornecedor
            fornecedor.cnpj = request.form["cnpj"]
            fornecedor.nome = request.form["nome"]
            fornecedor.endereco = request.form["endereco"]
            fornecedor.telefone = request.form["telefone"]
            fornecedor.email = request.form["email"]
            db.session.commit()
            flash("Fornecedor editado com sucesso!", "success")
        else:  # Novo fornecedor
            cnpj = request.form["cnpj"]
            nome = request.form["nome"]
            endereco = request.form["endereco"]
            telefone = request.form["telefone"]
            email = request.form["email"]

            fornecedor_existente = Fornecedor.query.filter_by(cnpj=cnpj).first()
            if fornecedor_existente:
                flash("Já existe um fornecedor com esse CNPJ!", "error")
                return redirect(url_for("gerenciar_fornecedores"))

            novo_fornecedor = Fornecedor(
                cnpj=cnpj, nome=nome, endereco=endereco, telefone=telefone, email=email
            )
            db.session.add(novo_fornecedor)
            db.session.commit()
            flash("Fornecedor adicionado com sucesso!", "success")

        return redirect(url_for("gerenciar_fornecedores"))

    fornecedores = Fornecedor.query.all()
    return render_template(
        "fornecedor.html", fornecedores=fornecedores, fornecedor=fornecedor
    )


@app.route("/excluir_fornecedor/<int:id>")
@login_required
def excluir_fornecedor(id):
    fornecedor = Fornecedor.query.get_or_404(id)
    db.session.delete(fornecedor)
    db.session.commit()
    flash("Fornecedor excluído com sucesso!", "success")
    return redirect(url_for("gerenciar_fornecedores"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = Usuario.query.filter_by(username=username).first()

        if user and user.check_password(password):
            session["user_id"] = user.id
            flash("Login realizado com sucesso!", "success")
            return redirect(url_for("index"))
        else:
            flash("Nome de usuário ou senha incorretos.", "error")

    return render_template("login.html")


@app.route("/logout")
@login_required
def logout():
    session.pop("user_id", None)
    flash("Logout realizado com sucesso!", "success")
    return redirect(url_for("login"))


if __name__ == "__main__":
    app.run(debug=True)
