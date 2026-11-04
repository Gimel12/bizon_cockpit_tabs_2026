
var containers = [];
var selectedContainer = {};
var machines = [];
var selectedMachine = {};
var py_path = "/usr/local/share/dlbt_os/cockpit_jupyter/py_backend/"
var global_path = "/usr/local/share/dlbt_os/gen/"
var container_marker = "-native_biz"
var jupyter_images = ["nvidia", "jupyter_test", container_marker]
var _docker_images_src = {
    "jupyter_test": "images/cuda.png",
    "nvcr.io/nvidia/tensorflow": "images/tensorflow.jpg",
    "pytorch": "images/pytorch.png",
    "cuda": "images/cuda.png",
    "nvidia": "images/cuda.png",
    "default": "images/docker.png"
}

_working_mode = "dev" //modes:  dev, production
_tab_name = "jupyter";

var _using_port = ""
var _docker_images = [];
var _jupyter_images = [];
var _img_parse_count = 0;
var _img_parse_incomplete = "";

function clean_name(name) {
    var idx = name.indexOf(container_marker);
    if (idx < 0)
        return name;
    return name.slice(0, idx) + name.slice(idx + container_marker.length);
}

function get_picture(img_tag) {
    var i;
    for (i in _docker_images_src) {
        if (img_tag.indexOf(i) >= 0) {
            return _docker_images_src[i]
        }
    }
    return _docker_images_src["default"]
}

function load_containers(username) {
    if (_working_mode == "production") {
        cockpit.spawn([py_path + "dist/read_images"])
            .then(process_images)
            .then(ping_success)
            .catch(console.log('Failed mode production of load_Containers'));
    } else {
        options = {
            
        }
        cockpit.spawn(["/usr/bin/python3", py_path + "read_images.py"], options)
            .then(process_images)
            .then(ping_success)
            .catch(load_container_info_fsp);
    }
}

function load_container_info_fsp() {
    console.log("failsafe");
    cockpit.spawn(["/usr/bin/python3", py_path + "read_images.py"])
        .then(process_images)
        .then(ping_success)
        .catch(showImageLoadError);
}

function real_parse_images(data) {
    console.log("this", data);
    var imgs = JSON.parse(data);

    _jupyter_images = imgs.filter(function (v) {
        return true;
    });
    _img_parse_count += 1;
}

function parse_images(data) {
    var lines = data.split('\n');
    var extralines = [];
    var start_p = !_img_parse_count ? 1 : 0;
    for (var i = start_p; i < lines.length; i++) {
        var words = lines[i].split(" ");
        var wordsf = words.filter(word => word !== " " && word !== "");
        if (wordsf.length < 7) {
            if (_img_parse_incomplete.length > 0) {
                extralines.push(_img_parse_incomplete + lines[i]);
            } else {
                _img_parse_incomplete = lines[i];
            }
        } else {
            _img_parse_incomplete = "";
            var new_item = {
                title: wordsf[0],
                repository: wordsf[0],
                tag: wordsf[1],
                id: wordsf[2],
                created: wordsf[3] + " " + wordsf[4] + " " + wordsf[5],
                size: wordsf[6]
            }
            _docker_images.push(new_item);
        }
    }

    extralines.forEach(line => {
        var words = line.split(" ").filter(word => word !== " " && word !== "");
        var new_item = {
            title: words[0],
            repository: words[0],
            tag: words[1],
            id: words[2],
            created: words[3] + " " + words[4] + " " + words[5],
            size: words[6]
        }
        _docker_images.push(new_item);
    });

    _jupyter_images = _docker_images.filter(function (v) {
        return jupyter_images.some(img => v.repository.indexOf(img) > -1);
    })
    _img_parse_count += 1;
}

function process_images(data) {
    real_parse_images(data);
    writeContainers();
    var button = document.getElementById("run_button");
    button.onclick = check_container_info;
    updateLaunchAvailability();
}

function writeContainers() {
    var containers = _jupyter_images;
    var elem = document.getElementById("containers-grid");
    elem.innerHTML = "";

    var elem_list = document.getElementById("containers-list");
    elem_list.innerHTML = "";

    var list_ul = document.createElement("ul");
    list_ul.classList.add("uk-list", "uk-list-striped", "uk-space");

    if (!containers.length) {
        const empty=document.createElement('div');empty.className='notebook-empty';empty.setAttribute('role','status');
        const copy=document.createElement('div');const title=document.createElement('strong');title.textContent='No notebook images yet';
        const detail=document.createElement('p');detail.textContent='Add a compatible notebook image in Docker Images, then come back here to start your workspace.';
        const link=document.createElement('a');link.href='../cockpit_containers/active_containers.html';link.textContent='Open Docker Images';
        link.dataset.cockpitRoute='/cockpit_containers/active_containers';
        copy.append(title,detail,link);empty.append(copy);elem.append(empty);
    }
    containers.forEach(function (container, index) {
        var bigDiv = document.createElement("div");
        var cardDiv = document.createElement("div");
        cardDiv.classList.add("uk-card", "uk-card-default", "custom-container");
        cardDiv.setAttribute('role','button');cardDiv.tabIndex=0;cardDiv.setAttribute('aria-pressed','false');
        cardDiv.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();cardDiv.click();}});

        var cardMedia = document.createElement("div");
        cardMedia.classList.add("uk-card-media-top");
        var img = new Image();
        img.src = get_picture(container.repository);
        img.alt="";

        cardDiv.addEventListener("click", function () {
            selectedContainer = containers[index];
            var allElements = document.getElementsByClassName("custom-container");
            Array.from(allElements).forEach(el => {el.classList.remove("seleted-card");el.setAttribute("aria-pressed","false");});
            this.classList.add("seleted-card");this.setAttribute("aria-pressed","true");
            updateLaunchAvailability();
        })

        var cardBody = document.createElement("div");
        cardBody.classList.add("uk-card-body", "uk-padding-small");
        var p = document.createElement("p");
        p.title = clean_name(container.title);
        p.classList.add("uk-text-truncate");
        p.appendChild(document.createTextNode(clean_name(container.title)))

        cardBody.appendChild(p);
        cardMedia.appendChild(img);
        cardDiv.appendChild(cardMedia);
        cardDiv.appendChild(cardBody);
        bigDiv.appendChild(cardDiv);
        elem.appendChild(bigDiv);

        var li = document.createElement("li");
        var li_input = document.createElement("input");
        li_input.name = "images-select";
        li_input.classList.add("uk-form-check");
        li_input.type = "radio";
        li_input.id = "image-" + container.id;

        li_input.addEventListener("click", function () {
            selectedContainer = containers[index];
        });
        li.appendChild(li_input);
        var span_image = document.createElement("span");
        span_image.classList.add("uk-icon", "uk-icon-image");
        span_image.style = "margin-left:8px;background-image: url(" + get_picture(container.repository) + ");";
        li.appendChild(span_image);
        var label_title = document.createElement("label");
        label_title.textContent = clean_name(container.title);
        label_title.style = "margin-left:8px;";
        li.appendChild(label_title);
        list_ul.appendChild(li);
    })

    elem_list.appendChild(list_ul);
}

function getAvailableMachines() {
    for (var i = 1; i <= 8; i++) {
        machines.push({ number: i });
    }
    return machines;
}

function writeAvailableMachines(){
    var machines = getAvailableMachines();
    var elem = document.getElementById("machine-grid");
    elem.innerHTML = "";
    machines.forEach(function(machine, index){

        var generalDiv = document.createElement("div");

        var card = document.createElement("div");
        card.classList.add("uk-card");
        card.classList.add("uk-card-secondary");
        card.classList.add("uk-card-body");
        card.classList.add("custom-machine");
        card.setAttribute('role','button');card.tabIndex=0;card.setAttribute('aria-pressed','false');
        card.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();card.click();}});

        var machinesHtml = document.getElementsByClassName("custom-machine");

        card.addEventListener("click", function(){
            selectedMachine = machines[index];
            console.log(selectedMachine);
            for(i = 0; i < machinesHtml.length; i++){
                machinesHtml[i].classList.remove("seleted-machine");machinesHtml[i].setAttribute("aria-pressed","false");
            }
            this.classList.add("seleted-machine");this.setAttribute("aria-pressed","true");
            updateLaunchAvailability();
        })
        var divText = document.createTextNode(machine.number + (machine.number===1 ? " GPU" : " GPUs"));
    
        generalDiv.appendChild(card);
        card.appendChild(divText);
    
        elem.appendChild(generalDiv);
    })
    
}

function run_jupyter(port) {
    const button=document.getElementById('run_button');
    if(button.getAttribute('aria-disabled')==='true')return;
    button.setAttribute('aria-disabled','true');button.textContent='Starting notebook…';
    const name=document.getElementById('name-notebook').value;
    const volume=$('#volume-bind-check').prop('checked')?$('#vol-host').val()+':'+$('#vol-container').val():'x';
    const args=['/usr/bin/python3',py_path+'start_container.py','--name='+name,'--image='+selectedContainer.id,'--gpus='+(selectedMachine?selectedMachine.number:1),'--port='+port,'--volume='+volume,'--extra='+$('#extra-option').val()];
    cockpit.spawn(args,{err:'message'}).then(()=>{window.top.location.assign('/cockpit_jupyter/active_containers');}).catch(err=>{UIkit.notification({message:err.message||'Notebook could not start',status:'danger',timeout:8000});}).always(()=>{button.removeAttribute('aria-disabled');button.textContent='Launch notebook';updateLaunchAvailability();});
}

function setCookie(cname, cvalue, exdays) {
    var d = new Date();
    d.setTime(d.getTime() + (exdays*24*60*60*1000));
    var expires = "expires="+ d.toUTCString();
    document.cookie = cname + "=" + cvalue + ";" + expires + ";path=/";
}

function getCookie(cname) {
    var name = cname + "=";
    var decodedCookie = decodeURIComponent(document.cookie);
    var ca = decodedCookie.split(';');
    for(var i = 0; i <ca.length; i++) {
      var c = ca[i];
      while (c.charAt(0) == ' ') {
        c = c.substring(1);
      }
      if (c.indexOf(name) == 0) {
        return c.substring(name.length, c.length);
      }
    }
    return "";
  }

function updateLaunchAvailability() {
    const button=document.getElementById('run_button');
    button.disabled=!selectedContainer.id || !selectedMachine.number;
}
function showImageLoadError() {
    const grid=document.getElementById('containers-grid');grid.textContent='';
    const box=document.createElement('div');box.className='notebook-empty';box.setAttribute('role','alert');
    box.textContent='Notebook images could not be loaded. Check that Docker is running, then refresh this page.';grid.append(box);
    document.getElementById('run_button').disabled=true;
}
function check_container_info(){
    if(!selectedContainer.id || !selectedMachine.number || document.getElementById('run_button').getAttribute('aria-disabled')==='true')return;
    if(_working_mode == "production"){
        cockpit.spawn([py_path + "dist/read_containers"])
        .then(check_ports)
        .then(ping_success)
        .catch(console.log('Failed mode production of check_container_info')); 
    }      
    else{
        cockpit.spawn(["/usr/bin/python3",py_path + "read_containers.py"])
        .then(check_ports)
        .then(ping_success)
        .catch(console.log('Failed mode dev of check_container_info')); 
    }
}


function check_ports(data){
    const used=new Set(JSON.parse(data).map(x=>Number(x.port)));
    for(let port=8888;port>=8800;port--){if(!used.has(port)){run_jupyter(port);return;}}
    UIkit.notification({message:'No free notebook port is available',status:'danger'});
}


function ping_success() {
    // result.style.color = "green";
    // result.innerHTML = "success";
    console.log("Success");
}

function ping_fail(data) {
    // result.style.color = "red";
    // result.innerHTML = "fail";
    console.log("Fail", data);
}


let stateCheck = setInterval(() => {
    if (document.readyState === 'complete') {
        console.log("dawg...");        
        clearInterval(stateCheck);
        document.body.style = "overflow:auto;";
        $("#volume-bind-check").click(function(){
            if($("#volume-bind-check").prop("checked")){
                $(".volume-bind").removeClass("hidden");
            }
            else{
                $(".volume-bind").addClass("hidden");
            }
        })
        cockpit.user().then(user => {
            load_containers(username = user.name);
            writeAvailableMachines();
        })        
    }
}, 500);
