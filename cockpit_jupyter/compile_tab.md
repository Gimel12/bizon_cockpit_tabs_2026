* Compile pythons
```
cd py_backend/
pyinstaller --onefile commit_container.py; pyinstaller --onefile read_containers.py; pyinstaller --onefile read_images.py; pyinstaller --onefile start_container.py; pyinstaller --onefile stop_all_containers.py; pyinstaller --onefile stop_container.py;
sudo rm -r build *.spec *.py __pycache__ ../*.md
```