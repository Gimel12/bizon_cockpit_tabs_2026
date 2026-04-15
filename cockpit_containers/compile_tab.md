## Steps

* Pyinstaller for the python scripts

* CSS files
  * http://cssobfuscator.com/done?_fid=yqg0

* Javascript
  * https://obfuscator.io/
  
* HTML
  * http://minifycode.com/html-minifier/

* Pythons
```
sudo rm *.md
cd py_backend/
pyinstaller --onefile erase_image.py; pyinstaller --onefile read_images.py;
sudo rm -r build *.spec *.py __pycache__
```