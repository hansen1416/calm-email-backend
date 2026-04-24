# Mysql

docker pull mysql:8.0

docker run -d \
  --name calm-mysql \
  -e MYSQL_ROOT_PASSWORD=root123456 \
  -e MYSQL_DATABASE=calm_email \
  -e MYSQL_USER=calm \
  -e MYSQL_PASSWORD=calm123456 \
  -p 3306:3306 \
  -v calm_mysql_data:/var/lib/mysql \
  mysql:8.0