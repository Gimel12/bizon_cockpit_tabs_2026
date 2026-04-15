var _update_finished = false;
var working_mode = 'production';

function update_tab(){
    var text = "You are about to download an update for this tab. Are you sure?";
    $("#update-text").html(text);
    var mod = document.getElementById("modal-update");
    UIkit.modal(mod).show();
}


// function update_webui(){
//     var text = "You are about to download an update for all the Bizon tabs. This might take a few minutes. Are you sure?";
//     $("#update-webui-text").html(text);
//     var mod = document.getElementById("modal-update-webui");
//     UIkit.modal(mod).show();
// }

function real_update_tab(){
    console.log("Starting update...");
    _update_finished = false;

    // $("#updating-spinner").removeClass("hidden");
    document.getElementById("updating-spinner").style.visibility = "visible";
    // $(".upd-spinner").show();
    if(working_mode == "production"){
        cockpit.spawn([py_path + "update_tab"])
        .stream(on_update)
        .then(update_success)
        .catch(update_fail); 
    }
    else{
        cockpit.spawn(["python3",py_path + "update_tab.py"])
        .stream(on_update)
        .then(update_success)
        .catch(update_fail); 
    }
}

// function real_update_webui(){
//     console.log("Starting update for all tabs...");
//     _update_finished = false;

//     // $("#updating-spinner").removeClass("hidden");
//     document.getElementById("updating-webui-spinner").style.visibility = "visible";
//     // $(".upd-spinner").show();
//     if(working_mode == "production"){
//         cockpit.spawn([py_path + "dist/update_tab", "--tabname=all" ])
//         .stream(on_update)
//         .then(update_success)
//         .catch(update_fail); 
//     }
//     else{
//         cockpit.spawn(["python3",py_path + "update_tab.py","--mode=dev","--tabname=all"])
//         .stream(on_update)
//         .then(update_success)
//         .catch(update_fail); 
//     }
// }

function on_cancel_update(){
    options = {
        "superuser":"try"
    } 
    if(working_mode == "production"){        
        cockpit.spawn(["killall","-9","update_tab"], options) //local testing
        .stream(on_update)
        .then(update_success)
        .catch(update_fail); 
    }
    else{
        cockpit.spawn(["killall","-9","python3"], options) //local testing
        .stream(on_update)
        .then(update_success)
        .catch(update_fail); 
    }
}

function update_fail(){
    var mod = document.getElementById("modal-update");
    UIkit.modal(mod).hide();        
    document.getElementById("updating-spinner").style.visibility = "hidden";
    UIkit.notification({
        message: 'The tab was not updated. Check your connection and try again.',
        status: 'danger',
        pos: 'top-center',
        timeout: 2000
    });
}

function update_success(){
    if(!_update_finished)
        return;
    var mod = document.getElementById("modal-update");
    UIkit.modal(mod).hide();    
    document.getElementById("updating-spinner").style.visibility = "hidden";
    UIkit.notification({
        message: 'The tab(s) was updated successfully. Please refresh the page to load the changes.',
        status: 'success',
        pos: 'top-center',
        timeout: 2000
    });
}

function on_update(data){
    // console.log(data);
    console.log("Inside it...");  
    _update_finished = true;
}

let stateCheck2 = setInterval(() => {
    if (document.readyState === 'complete') {
        //usage  
        clearInterval(stateCheck2);      
        $("#update").click(update_tab);        
        $("#update-tab-btn").click(real_update_tab);
        $("#cancel-update-tab-btn").click(on_cancel_update);
        // $("#update-webui").click(update_webui);        
        // $("#update-webui-btn").click(real_update_webui);
        // $("#cancel-update-webui-btn").click(on_cancel_update);
        document.getElementById("updating-spinner").style.visibility = "hidden";
        document.getElementById("updating-webui-spinner").style.visibility = "hidden";
    }
}, 1000);